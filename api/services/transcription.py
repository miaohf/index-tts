"""基于 faster-whisper 的语音转写服务。"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Literal

from api.config import (
    whisper_compute_type,
    whisper_device,
    whisper_download_root,
    whisper_model_size,
)

logger = logging.getLogger("indextts2-stt")

ResponseFormat = Literal["json", "text", "srt", "verbose_json", "vtt"]

_model = None
_model_lock = threading.Lock()


@dataclass
class TranscriptionResult:
    text: str
    language: str
    duration: float
    segments: list[dict[str, Any]]


def _get_whisper_model():
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(
                "未安装 faster-whisper，请执行: uv sync --extra asr"
            ) from e

        device = whisper_device()
        compute_type = whisper_compute_type(device)
        model_size = whisper_model_size()
        download_root = whisper_download_root()

        kwargs: dict[str, Any] = {
            "device": device,
            "compute_type": compute_type,
        }
        if download_root:
            kwargs["download_root"] = download_root

        logger.info(
            "Loading faster-whisper model=%s device=%s compute_type=%s",
            model_size,
            device,
            compute_type,
        )
        _model = WhisperModel(model_size, **kwargs)
        logger.info("faster-whisper model loaded")
        return _model


def _normalize_model_name(model: str) -> None:
    """OpenAI 客户端常传 whisper-1；实际模型由环境变量配置。"""
    name = (model or "").strip()
    if not name:
        raise ValueError("model 不能为空")
    allowed = {"whisper-1", whisper_model_size()}
    if name not in allowed:
        raise ValueError(
            f"不支持的 model: {name!r}，可用: whisper-1 或 {whisper_model_size()!r}"
        )


def _format_timestamp_srt(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _segment_to_dict(segment: Any) -> dict[str, Any]:
    return {
        "id": segment.id,
        "seek": segment.seek,
        "start": segment.start,
        "end": segment.end,
        "text": segment.text,
        "tokens": segment.tokens,
        "temperature": getattr(segment, "temperature", None),
        "avg_logprob": segment.avg_logprob,
        "compression_ratio": segment.compression_ratio,
        "no_speech_prob": segment.no_speech_prob,
    }


def _format_srt(segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for i, seg in enumerate(segments, 1):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        blocks.append(
            f"{i}\n"
            f"{_format_timestamp_srt(seg['start'])} --> {_format_timestamp_srt(seg['end'])}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)


def _format_vtt(segments: list[dict[str, Any]]) -> str:
    lines = ["WEBVTT", ""]
    for i, seg in enumerate(segments, 1):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(
            f"{_format_timestamp_vtt(seg['start'])} --> {_format_timestamp_vtt(seg['end'])}"
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def transcribe_file_sync(
    audio_path: str,
    *,
    model: str = "whisper-1",
    language: str | None = None,
    prompt: str | None = None,
    temperature: float = 0.0,
) -> TranscriptionResult:
    _normalize_model_name(model)
    whisper = _get_whisper_model()

    lang = language.strip() if language and language.strip() else None
    initial_prompt = prompt.strip() if prompt and prompt.strip() else None

    segments_iter, info = whisper.transcribe(
        audio_path,
        language=lang,
        initial_prompt=initial_prompt,
        temperature=temperature,
        beam_size=5,
        vad_filter=True,
    )
    segments = [_segment_to_dict(seg) for seg in segments_iter]
    text = "".join(seg["text"] for seg in segments).strip()
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    detected_language = getattr(info, "language", None) or lang or "unknown"

    return TranscriptionResult(
        text=text,
        language=detected_language,
        duration=duration,
        segments=segments,
    )


def build_transcription_response(
    result: TranscriptionResult,
    *,
    response_format: ResponseFormat,
) -> str | dict[str, Any]:
    if response_format == "text":
        return result.text

    if response_format == "json":
        return {"text": result.text}

    if response_format == "verbose_json":
        return {
            "task": "transcribe",
            "language": result.language,
            "duration": result.duration,
            "text": result.text,
            "segments": result.segments,
        }

    if response_format == "srt":
        return _format_srt(result.segments)

    if response_format == "vtt":
        return _format_vtt(result.segments)

    raise ValueError(f"不支持的 response_format: {response_format}")


async def transcribe_upload(
    content: bytes,
    filename: str,
    *,
    model: str = "whisper-1",
    language: str | None = None,
    prompt: str | None = None,
    response_format: ResponseFormat = "json",
    temperature: float = 0.0,
) -> str | dict[str, Any]:
    suffix = os.path.splitext(filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await asyncio.to_thread(
            transcribe_file_sync,
            tmp_path,
            model=model,
            language=language,
            prompt=prompt,
            temperature=temperature,
        )
        logger.info(
            "Transcribed text: %s (language=%s, duration=%.2fs)",
            f"{result.text[:50]}...",
            result.language,
            result.duration,
        )
        return build_transcription_response(result, response_format=response_format)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
