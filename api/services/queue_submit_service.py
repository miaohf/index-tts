from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any

from fastapi import HTTPException
from fastapi.responses import Response

from api.redis_queue import (
    audio_key,
    bytes_to_text,
    client_request_key,
    encode_job_message,
    get_redis_client,
    group_audio_key,
    group_key,
    hash_to_text_map,
    job_key,
    job_ttl_seconds,
    max_request_size,
    new_job_id,
    now_ts,
    queue_name,
    request_key,
    request_queue_name,
)
from api.utils.audio import merge_wav_bytes

from api.services.queue_status import QueueStatus

logger = logging.getLogger("indextts2-api")

WAIT_POLL_INTERVAL_SECONDS = 0.2
DEFAULT_WAIT_TIMEOUT_SECONDS = 180
MAX_WAIT_TIMEOUT_SECONDS = 1800


def _sync_wait_timeout_exceeded(request_id: str, wait_timeout_seconds: int, status: str, **extra: Any) -> None:
    detail: dict[str, Any] = {
        "request_id": request_id,
        "status": status,
        "message": (
            f"合成在 {wait_timeout_seconds}s 内未完成，请增大 POST 查询参数 wait_timeout_seconds（最大 {MAX_WAIT_TIMEOUT_SECONDS}）后重试"
        ),
    }
    detail.update(extra)
    raise HTTPException(status_code=504, detail=detail)


# 超过此字符数时触发多 GPU 分段并发；0 表示禁用。默认只拆真正的长文本，避免普通句子被切开。
AUTO_SPLIT_THRESHOLD = int(os.getenv("INDEX_TTS_AUTO_SPLIT_THRESHOLD", "1200"))
# 每段目标最大字符数。实际分段会为避免极短尾段而允许少量超出。
AUTO_SPLIT_SEGMENT_LENGTH = int(os.getenv("INDEX_TTS_AUTO_SPLIT_SEGMENT_LENGTH", "1000"))


def to_payload(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def should_split(text: str) -> bool:
    return AUTO_SPLIT_THRESHOLD > 0 and len(text) > AUTO_SPLIT_THRESHOLD


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _get_request_info(client: Any, request_id: str) -> dict[str, str] | None:
    raw = client.hgetall(request_key(request_id))
    if not raw:
        return None
    return hash_to_text_map(raw)


def _try_reserve_client_request_id(client: Any, client_req_id: str, request_id: str, ttl: int) -> tuple[bool, str]:
    map_key = client_request_key(client_req_id)
    existed = bytes_to_text(client.get(map_key))
    if existed:
        return False, existed

    ok = client.set(map_key, request_id, ex=ttl, nx=True)
    if ok:
        return True, request_id

    existed = bytes_to_text(client.get(map_key))
    if existed:
        return False, existed
    return True, request_id


async def _build_replay_response(
    client: Any,
    request_id: str,
    request_type: str,
    payload_fingerprint: str,
    wait_timeout_seconds: int,
) -> Response:
    info = _get_request_info(client, request_id=request_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"幂等请求映射存在但请求记录已过期: {request_id}")

    existing_type = info.get("request_type")
    if existing_type and existing_type != request_type:
        raise HTTPException(status_code=409, detail=f"client_request_id 已被其他请求类型占用: {existing_type}")

    existing_fingerprint = info.get("payload_fingerprint")
    if existing_fingerprint and existing_fingerprint != payload_fingerprint:
        raise HTTPException(status_code=409, detail="client_request_id 重复使用，但请求参数不一致")

    status = info.get("status", QueueStatus.UNKNOWN.value)
    job_id = info.get("job_id")
    group_id = info.get("group_id")
    if status == QueueStatus.DONE.value:
        if job_id:
            audio = client.get(audio_key(job_id))
            if audio:
                return Response(content=audio, media_type="audio/wav")
        if group_id:
            audio = client.get(group_audio_key(group_id))
            if audio:
                return Response(content=audio, media_type="audio/wav")
        raise HTTPException(status_code=404, detail=f"幂等请求已完成但音频已过期: {request_id}")

    if status == QueueStatus.FAILED.value:
        error = info.get("error", "unknown error")
        raise HTTPException(status_code=500, detail=f"TTS 任务失败: {error}")

    from api.services.queue_query_service import wait_for_request_audio_content

    audio = await wait_for_request_audio_content(request_id, wait_timeout_seconds)
    return Response(content=audio, media_type="audio/wav")


def _count_active_requests(client: Any) -> int:
    rq_name = request_queue_name()
    total_requests = 0
    stale_ids: list[str] = []

    request_ids = [rid.decode("utf-8") for rid in client.zrange(rq_name, 0, -1)]
    for request_id in request_ids:
        raw = client.hgetall(request_key(request_id))
        if not raw:
            stale_ids.append(request_id)
            continue
        info = hash_to_text_map(raw)
        status = info.get("status")
        if status in {QueueStatus.QUEUED.value, QueueStatus.PROCESSING.value}:
            total_requests += 1
            continue
        stale_ids.append(request_id)

    if stale_ids:
        client.zrem(rq_name, *stale_ids)
    # 活跃请求集合长期为空时允许自动过期，避免残留空 key。
    client.expire(rq_name, max(120, job_ttl_seconds()))
    return total_requests


def _ensure_request_capacity(client: Any) -> None:
    current_requests = _count_active_requests(client)
    request_cap = max_request_size()
    if current_requests >= request_cap:
        raise HTTPException(
            status_code=503,
            detail=f"请求已达上限（{current_requests}/{request_cap}），请稍后重试",
        )


def _register_request(
    client: Any,
    request_type: str,
    ttl: int,
    payload_fingerprint: str,
    client_req_id: str | None,
) -> tuple[str, str, bool]:
    request_id = new_job_id()
    if client_req_id:
        is_new, resolved_request_id = _try_reserve_client_request_id(
            client=client,
            client_req_id=client_req_id,
            request_id=request_id,
            ttl=ttl,
        )
        if not is_new:
            return resolved_request_id, request_key(resolved_request_id), False
        request_id = resolved_request_id
    r_key = request_key(request_id)
    ts = str(now_ts())
    mapping: dict[str, str] = {
        "status": QueueStatus.QUEUED.value,
        "request_type": request_type,
        "payload_fingerprint": payload_fingerprint,
        "created_at": ts,
        "updated_at": ts,
    }
    if client_req_id:
        mapping["client_request_id"] = client_req_id
    client.hset(r_key, mapping=mapping)
    client.expire(r_key, ttl)
    client.zadd(request_queue_name(), {request_id: now_ts()})
    client.expire(request_queue_name(), ttl)
    return request_id, r_key, True


def _mark_request_status(client: Any, r_key: str, status: QueueStatus, **extra_fields: str) -> None:
    mapping: dict[str, str] = {"status": status.value, "updated_at": str(now_ts())}
    mapping.update(extra_fields)
    client.hset(r_key, mapping=mapping)


def _finish_request(client: Any, request_id: str, r_key: str, ttl: int, status: QueueStatus, **extra_fields: str) -> None:
    _mark_request_status(client, r_key, status=status, **extra_fields)
    client.expire(r_key, ttl)
    client.zrem(request_queue_name(), request_id)


async def enqueue_and_wait(
    request_type: str,
    payload: dict[str, Any],
    wait_timeout_seconds: int,
    client_request_id: str | None = None,
) -> Response:
    client = get_redis_client()
    payload_fingerprint = _payload_fingerprint(payload)
    if client_request_id:
        map_key = client_request_key(client_request_id)
        mapped_request_id = bytes_to_text(client.get(map_key))
        if mapped_request_id:
            if not _get_request_info(client, request_id=mapped_request_id):
                client.delete(map_key)
            else:
                return await _build_replay_response(
                    client=client,
                    request_id=mapped_request_id,
                    request_type=request_type,
                    payload_fingerprint=payload_fingerprint,
                    wait_timeout_seconds=wait_timeout_seconds,
                )
    _ensure_request_capacity(client)
    q_name = queue_name()

    ttl = job_ttl_seconds()
    request_id, r_key, is_new_request = _register_request(
        client=client,
        request_type=request_type,
        ttl=ttl,
        payload_fingerprint=payload_fingerprint,
        client_req_id=client_request_id,
    )
    if client_request_id and not is_new_request:
        return await _build_replay_response(
            client=client,
            request_id=request_id,
            request_type=request_type,
            payload_fingerprint=payload_fingerprint,
            wait_timeout_seconds=wait_timeout_seconds,
        )
    job_id = new_job_id()
    j_key = job_key(job_id)
    a_key = audio_key(job_id)
    ts = str(now_ts())

    client.hset(
        j_key,
        mapping={
            "status": QueueStatus.QUEUED.value,
            "request_type": request_type,
            "request_id": request_id,
            "created_at": ts,
            "updated_at": ts,
        },
    )
    client.expire(j_key, ttl)
    _mark_request_status(client, r_key=r_key, status=QueueStatus.QUEUED, job_id=job_id)
    client.expire(r_key, ttl)
    client.rpush(q_name, encode_job_message(job_id=job_id, request_type=request_type, payload=payload))

    deadline = time.time() + wait_timeout_seconds
    while time.time() < deadline:
        info_raw = client.hgetall(j_key)
        if not info_raw:
            raise HTTPException(status_code=500, detail=f"任务状态丢失: {job_id}")
        info = hash_to_text_map(info_raw)
        status = info.get("status")
        if status == QueueStatus.DONE.value:
            audio = client.get(a_key)
            if not audio:
                raise HTTPException(status_code=500, detail=f"任务完成但音频不存在: {job_id}")
            _finish_request(
                client,
                request_id=request_id,
                r_key=r_key,
                ttl=ttl,
                status=QueueStatus.DONE,
                job_id=job_id,
            )
            return Response(content=audio, media_type="audio/wav")
        if status == QueueStatus.FAILED.value:
            error = info.get("error", "unknown error")
            _finish_request(
                client,
                request_id=request_id,
                r_key=r_key,
                ttl=ttl,
                status=QueueStatus.FAILED,
                job_id=job_id,
                error=error,
            )
            raise HTTPException(status_code=500, detail=f"TTS 任务失败: {error}")
        await asyncio.sleep(WAIT_POLL_INTERVAL_SECONDS)

    info_raw = client.hgetall(j_key)
    status = QueueStatus.UNKNOWN.value
    if info_raw:
        status = hash_to_text_map(info_raw).get("status", status)
    _sync_wait_timeout_exceeded(request_id, wait_timeout_seconds, status)


async def enqueue_group_and_wait(
    request_type: str,
    base_payload: dict[str, Any],
    segments: list[str],
    wait_timeout_seconds: int,
    interval_silence_ms: int,
    client_request_id: str | None = None,
) -> Response:
    client = get_redis_client()
    payload_fingerprint = _payload_fingerprint(base_payload)
    if client_request_id:
        map_key = client_request_key(client_request_id)
        mapped_request_id = bytes_to_text(client.get(map_key))
        if mapped_request_id:
            if not _get_request_info(client, request_id=mapped_request_id):
                client.delete(map_key)
            else:
                return await _build_replay_response(
                    client=client,
                    request_id=mapped_request_id,
                    request_type=request_type,
                    payload_fingerprint=payload_fingerprint,
                    wait_timeout_seconds=wait_timeout_seconds,
                )
    _ensure_request_capacity(client)
    q_name = queue_name()
    needed = len(segments)

    ttl = job_ttl_seconds()
    request_id, r_key, is_new_request = _register_request(
        client=client,
        request_type=request_type,
        ttl=ttl,
        payload_fingerprint=payload_fingerprint,
        client_req_id=client_request_id,
    )
    if client_request_id and not is_new_request:
        return await _build_replay_response(
            client=client,
            request_id=request_id,
            request_type=request_type,
            payload_fingerprint=payload_fingerprint,
            wait_timeout_seconds=wait_timeout_seconds,
        )
    group_id = new_job_id()
    ts = str(now_ts())
    sub_job_ids: list[str] = []

    for i, seg_text in enumerate(segments):
        sub_id = new_job_id()
        payload = {**base_payload, "text": seg_text}
        j_key = job_key(sub_id)
        client.hset(
            j_key,
            mapping={
                "status": QueueStatus.QUEUED.value,
                "request_type": request_type,
                "request_id": request_id,
                "created_at": ts,
                "updated_at": ts,
                "group_id": group_id,
                "segment_index": str(i),
                "total_segments": str(needed),
            },
        )
        client.expire(j_key, ttl)
        client.rpush(
            q_name,
            encode_job_message(job_id=sub_id, request_type=request_type, payload=payload),
        )
        sub_job_ids.append(sub_id)
        logger.info(
            "Group %s: submitted sub-job %s (%d/%d) text=%s…",
            group_id,
            sub_id,
            i + 1,
            needed,
            seg_text[:20],
        )
        # 每投递一个分片就让出一次事件循环，降低组级阻塞。
        await asyncio.sleep(0)

    g_key = group_key(group_id)
    client.hset(
        g_key,
        mapping={
            "status": QueueStatus.PROCESSING.value,
            "request_id": request_id,
            "interval_silence_ms": str(interval_silence_ms),
            "total": str(needed),
            "done_count": "0",
            "job_ids": ",".join(sub_job_ids),
            "created_at": ts,
            "updated_at": ts,
        },
    )
    client.expire(g_key, ttl)
    _mark_request_status(client, r_key=r_key, status=QueueStatus.QUEUED, group_id=group_id)
    client.expire(r_key, ttl)

    deadline = time.time() + wait_timeout_seconds
    while time.time() < deadline:
        done_count = 0
        failed_error: str | None = None

        for sub_id in sub_job_ids:
            info_raw = client.hgetall(job_key(sub_id))
            if not info_raw:
                failed_error = f"子任务状态丢失: {sub_id}"
                break
            info = hash_to_text_map(info_raw)
            status = info.get("status")
            if status == QueueStatus.FAILED.value:
                failed_error = info.get("error", "unknown error")
                break
            if status == QueueStatus.DONE.value:
                done_count += 1

        if failed_error:
            client.hset(
                g_key,
                mapping={
                    "status": QueueStatus.FAILED.value,
                    "error": failed_error,
                    "updated_at": str(now_ts()),
                },
            )
            _finish_request(
                client,
                request_id=request_id,
                r_key=r_key,
                ttl=ttl,
                status=QueueStatus.FAILED,
                group_id=group_id,
                error=failed_error,
            )
            raise HTTPException(status_code=500, detail=f"分段子任务失败: {failed_error}")

        if done_count == needed:
            wav_bytes_list: list[bytes] = []
            for sub_id in sub_job_ids:
                audio = client.get(audio_key(sub_id))
                if not audio:
                    raise HTTPException(status_code=500, detail=f"子任务音频数据丢失: {sub_id}")
                wav_bytes_list.append(audio)

            merged = merge_wav_bytes(wav_bytes_list, interval_silence_ms=interval_silence_ms)

            g_audio_key = group_audio_key(group_id)
            client.set(g_audio_key, merged, ex=ttl)
            client.hset(
                g_key,
                mapping={
                    "status": QueueStatus.DONE.value,
                    "done_count": str(needed),
                    "updated_at": str(now_ts()),
                },
            )
            _finish_request(
                client,
                request_id=request_id,
                r_key=r_key,
                ttl=ttl,
                status=QueueStatus.DONE,
                group_id=group_id,
            )
            logger.info("Group %s: all %d segments done, merged audio %.1f KB", group_id, needed, len(merged) / 1024)
            return Response(content=merged, media_type="audio/wav")

        client.hset(g_key, mapping={"done_count": str(done_count), "updated_at": str(now_ts())})
        await asyncio.sleep(WAIT_POLL_INTERVAL_SECONDS)

    g_raw = client.hgetall(g_key)
    group_status = QueueStatus.UNKNOWN.value
    if g_raw:
        group_status = hash_to_text_map(g_raw).get("status", group_status)
    _sync_wait_timeout_exceeded(
        request_id,
        wait_timeout_seconds,
        group_status,
        job_ids=sub_job_ids,
        total_segments=needed,
    )

