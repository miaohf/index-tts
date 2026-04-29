#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import logging
import os
import signal
from pathlib import Path
from typing import Any

import soundfile as sf

from api.redis_queue import (
    audio_key,
    decode_job_message,
    get_redis_client,
    hash_to_text_map,
    job_key,
    job_ttl_seconds,
    now_ts,
    queue_name,
    request_key,
    request_queue_name,
)

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("indextts2-worker")
_STOP = False


def _install_signal_handlers() -> None:
    def _handler(_sig: int, _frame: object) -> None:
        global _STOP
        _STOP = True

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _encode_wav_bytes(wav_data: Any, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, wav_data, sample_rate, format="wav")
    return buf.getvalue()


def _run_job(model: Any, request_type: str, payload: dict[str, Any]) -> tuple[Any, int]:
    if request_type == "tts_v1":
        return model.generate_speech(
            text=payload["text"],
            prompt_speech_path=payload.get("prompt_speech_path"),
            speaker=payload.get("speaker"),
            temperature=payload.get("temperature", 0.8),
            top_k=payload.get("top_k", 30),
            top_p=payload.get("top_p", 0.8),
            seed=payload.get("seed", 421),
            max_text_tokens_per_segment=payload.get("max_text_tokens_per_sentence", 120),
            max_mel_tokens=payload.get("max_mel_tokens", 1500),
            num_beams=payload.get("num_beams", 3),
            length_penalty=payload.get("length_penalty", 0.0),
            repetition_penalty=payload.get("repetition_penalty", 10.0),
            emo_control_mode=0,
        )
    if request_type == "tts_v2":
        return model.generate_speech(
            text=payload["text"],
            prompt_speech_path=payload.get("prompt_speech_path"),
            speaker=payload.get("speaker"),
            temperature=payload.get("temperature", 0.8),
            top_k=payload.get("top_k", 30),
            top_p=payload.get("top_p", 0.8),
            seed=payload.get("seed", 421),
            max_text_tokens_per_segment=payload.get("max_text_tokens_per_segment", 120),
            max_mel_tokens=payload.get("max_mel_tokens", 1500),
            num_beams=payload.get("num_beams", 3),
            length_penalty=payload.get("length_penalty", 0.0),
            repetition_penalty=payload.get("repetition_penalty", 10.0),
            do_sample=payload.get("do_sample", True),
            emo_audio_prompt=payload.get("emo_audio_prompt"),
            emo_alpha=payload.get("emo_alpha", 1.0),
            emo_vector=payload.get("emo_vector"),
            use_emo_text=payload.get("use_emo_text", False),
            emo_text=payload.get("emo_text"),
            use_random=payload.get("use_random", False),
            interval_silence=payload.get("interval_silence", 200),
            emo_control_mode=payload.get("emo_control_mode", 0),
        )
    raise ValueError(f"unsupported request type: {request_type}")


def _finish_single_request_if_needed(
    client: Any,
    j_key: str,
    status: str,
    ttl: int,
    error: str | None = None,
) -> None:
    raw = client.hgetall(j_key)
    if not raw:
        return
    info = hash_to_text_map(raw)
    request_id = info.get("request_id")
    group_id = info.get("group_id")
    if not request_id or group_id:
        return

    r_key = request_key(request_id)
    mapping: dict[str, str] = {
        "status": status,
        "updated_at": str(now_ts()),
        "job_id": info.get("job_id") or j_key.rsplit(":", 1)[-1],
        "task_type": "job",
        "task_id": info.get("job_id") or j_key.rsplit(":", 1)[-1],
    }
    if error:
        mapping["error"] = error
    client.hset(r_key, mapping=mapping)
    client.expire(r_key, ttl)
    client.zrem(request_queue_name(), request_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="IndexTTS GPU Worker（Redis 队列消费者）")
    parser.add_argument("--gpu-id", type=int, required=True, help="物理 GPU 编号（0-based）")
    parser.add_argument("--redis-url", default=os.getenv("INDEX_TTS_REDIS_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument("--queue-name", default=os.getenv("INDEX_TTS_QUEUE_NAME", queue_name()))
    parser.add_argument("--job-ttl-seconds", type=int, default=job_ttl_seconds())
    parser.add_argument("--brpop-timeout", type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    _install_signal_handlers()
    os.chdir(ROOT)

    # 在导入模型前绑定到目标物理 GPU，避免误占其他卡。
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu_id)
    from api.inference import model  # pylint: disable=import-outside-toplevel

    client = get_redis_client(args.redis_url)
    logger.info(
        "Worker started, physical_gpu=%s, visible=%s, queue=%s",
        args.gpu_id,
        os.getenv("CUDA_VISIBLE_DEVICES"),
        args.queue_name,
    )

    while not _STOP:
        item = client.brpop(args.queue_name, timeout=args.brpop_timeout)
        if item is None:
            continue

        _q_name, raw_job = item
        try:
            msg = decode_job_message(raw_job)
            job_id = str(msg["job_id"])
            request_type = str(msg["request_type"])
            payload = msg["payload"]
        except Exception as e:
            logger.error("Failed to decode queue message: %s", e, exc_info=True)
            continue

        j_key = job_key(job_id)
        a_key = audio_key(job_id)
        ts = str(now_ts())
        client.hset(j_key, mapping={"status": "processing", "updated_at": ts, "worker_gpu": str(args.gpu_id)})
        client.expire(j_key, args.job_ttl_seconds)

        try:
            wav_data, sample_rate = _run_job(model=model, request_type=request_type, payload=payload)
            audio_bytes = _encode_wav_bytes(wav_data, sample_rate)
            client.set(a_key, audio_bytes, ex=args.job_ttl_seconds)
            client.hset(
                j_key,
                mapping={
                    "status": "done",
                    "sample_rate": str(sample_rate),
                    "updated_at": str(now_ts()),
                    "audio_key": a_key,
                },
            )
            client.expire(j_key, args.job_ttl_seconds)
            _finish_single_request_if_needed(
                client=client,
                j_key=j_key,
                status="done",
                ttl=args.job_ttl_seconds,
            )
        except Exception as e:
            logger.error("Job failed: %s (%s)", job_id, e, exc_info=True)
            client.hset(
                j_key,
                mapping={
                    "status": "failed",
                    "error": str(e),
                    "updated_at": str(now_ts()),
                },
            )
            client.expire(j_key, args.job_ttl_seconds)
            _finish_single_request_if_needed(
                client=client,
                j_key=j_key,
                status="failed",
                ttl=args.job_ttl_seconds,
                error=str(e),
            )

    logger.info("Worker exit requested, stop loop")


if __name__ == "__main__":
    main()
