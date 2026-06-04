from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException

from api.redis_queue import (
    audio_key,
    get_redis_client,
    group_audio_key,
    group_key,
    hash_to_text_map,
    job_ttl_seconds,
    job_key,
    now_ts,
    request_key,
    request_queue_name,
)
from api.utils.audio import merge_wav_bytes
from api.services.queue_status import QueueStatus
from api.services.queue_submit_service import WAIT_POLL_INTERVAL_SECONDS


def _to_int(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _read_hash_text(client, key: str) -> dict[str, str] | None:
    raw = client.hgetall(key)
    if not raw:
        return None
    return hash_to_text_map(raw)


def _finalize_request_status(client, request_id: str, status: QueueStatus, **extra: str) -> None:
    ttl = job_ttl_seconds()
    mapping: dict[str, str] = {
        "status": status.value,
        "updated_at": str(now_ts()),
    }
    mapping.update(extra)
    client.hset(request_key(request_id), mapping=mapping)
    client.expire(request_key(request_id), ttl)
    client.zrem(request_queue_name(), request_id)


def _refresh_single_request(client, request_id: str, info: dict[str, str]) -> dict[str, str]:
    status = info.get("status")
    if status in {QueueStatus.DONE.value, QueueStatus.FAILED.value}:
        return info

    job_id = info.get("job_id")
    if not job_id:
        return info

    job_info = _read_hash_text(client, job_key(job_id))
    if not job_info:
        return info

    job_status = job_info.get("status")
    if job_status == QueueStatus.DONE.value:
        _finalize_request_status(client, request_id, QueueStatus.DONE, job_id=job_id)
    elif job_status == QueueStatus.FAILED.value:
        _finalize_request_status(
            client,
            request_id,
            QueueStatus.FAILED,
            job_id=job_id,
            error=job_info.get("error", "unknown error"),
        )
    else:
        client.hset(
            request_key(request_id),
            mapping={"status": job_status or QueueStatus.UNKNOWN.value, "updated_at": str(now_ts())},
        )
    refreshed = _read_hash_text(client, request_key(request_id))
    return refreshed or info


def _refresh_group_request(client, request_id: str, info: dict[str, str]) -> dict[str, str]:
    group_id = info.get("group_id")
    if not group_id:
        return info

    g_key = group_key(group_id)
    group_info = _read_hash_text(client, g_key)
    if not group_info:
        return info

    group_status = group_info.get("status")
    if group_status in {QueueStatus.DONE.value, QueueStatus.FAILED.value}:
        # 兼容历史异常：group 已终态但 request 未终态。
        if info.get("status") not in {QueueStatus.DONE.value, QueueStatus.FAILED.value}:
            if group_status == QueueStatus.DONE.value:
                _finalize_request_status(client, request_id, QueueStatus.DONE, group_id=group_id)
            else:
                _finalize_request_status(
                    client,
                    request_id,
                    QueueStatus.FAILED,
                    group_id=group_id,
                    error=group_info.get("error", "unknown error"),
                )
        refreshed = _read_hash_text(client, request_key(request_id))
        return refreshed or info

    job_ids = [jid for jid in group_info.get("job_ids", "").split(",") if jid]
    if not job_ids:
        return info

    done_count = 0
    processing_count = 0
    queued_count = 0
    failed_error: str | None = None
    wav_bytes_list: list[bytes] = []

    for jid in job_ids:
        job_info = _read_hash_text(client, job_key(jid))
        if not job_info:
            queued_count += 1
            continue
        job_status = job_info.get("status")
        if job_status == QueueStatus.FAILED.value:
            failed_error = job_info.get("error", "unknown error")
            break
        if job_status == QueueStatus.DONE.value:
            audio = client.get(audio_key(jid))
            if not audio:
                queued_count += 1
                continue
            wav_bytes_list.append(audio)
            done_count += 1
        elif job_status == QueueStatus.PROCESSING.value:
            processing_count += 1
        else:
            queued_count += 1

    ttl = job_ttl_seconds()
    if failed_error:
        client.hset(
            g_key,
            mapping={
                "status": QueueStatus.FAILED.value,
                "error": failed_error,
                "done_count": str(done_count),
                "updated_at": str(now_ts()),
            },
        )
        client.expire(g_key, ttl)
        _finalize_request_status(client, request_id, QueueStatus.FAILED, group_id=group_id, error=failed_error)
    elif done_count == len(job_ids):
        merged = client.get(group_audio_key(group_id))
        if not merged:
            # 202 超时后兜底：在查询阶段完成合并，确保请求可达 done。
            interval_silence_ms = _to_int(group_info.get("interval_silence_ms")) or 200
            merged = merge_wav_bytes(wav_bytes_list, interval_silence_ms=interval_silence_ms)
            client.set(group_audio_key(group_id), merged, ex=ttl)
        client.hset(
            g_key,
            mapping={
                "status": QueueStatus.DONE.value,
                "done_count": str(done_count),
                "updated_at": str(now_ts()),
            },
        )
        client.expire(g_key, ttl)
        _finalize_request_status(client, request_id, QueueStatus.DONE, group_id=group_id)
    else:
        next_status = QueueStatus.PROCESSING.value if processing_count > 0 else QueueStatus.QUEUED.value
        client.hset(
            g_key,
            mapping={
                "status": next_status,
                "done_count": str(done_count),
                "updated_at": str(now_ts()),
            },
        )
        client.expire(g_key, ttl)
        client.hset(
            request_key(request_id),
            mapping={"status": next_status, "updated_at": str(now_ts())},
        )

    refreshed = _read_hash_text(client, request_key(request_id))
    return refreshed or info


def _refresh_request_state(client, request_id: str, info: dict[str, str]) -> dict[str, str]:
    if info.get("group_id"):
        return _refresh_group_request(client, request_id, info)
    return _refresh_single_request(client, request_id, info)


def refresh_request_state_by_id(client, request_id: str) -> dict[str, str] | None:
    info = _read_hash_text(client, request_key(request_id))
    if not info:
        return None
    return _refresh_request_state(client, request_id, info)


def get_job_detail(job_id: str) -> dict[str, str | None]:
    client = get_redis_client()
    raw = client.hgetall(job_key(job_id))
    if not raw:
        raise HTTPException(status_code=404, detail=f"任务不存在或已过期: {job_id}")
    info = hash_to_text_map(raw)
    return {
        "job_id": job_id,
        "status": info.get("status", QueueStatus.UNKNOWN.value),
        "request_id": info.get("request_id"),
        "request_type": info.get("request_type"),
        "group_id": info.get("group_id"),
        "segment_index": info.get("segment_index"),
        "total_segments": info.get("total_segments"),
        "created_at": info.get("created_at"),
        "updated_at": info.get("updated_at"),
        "error": info.get("error"),
    }


def get_job_audio_content(job_id: str) -> bytes:
    client = get_redis_client()
    raw = client.hgetall(job_key(job_id))
    if not raw:
        raise HTTPException(status_code=404, detail=f"任务不存在或已过期: {job_id}")
    info = hash_to_text_map(raw)
    status = info.get("status")
    if status != QueueStatus.DONE.value:
        raise HTTPException(status_code=409, detail=f"任务尚未完成: {status}")
    audio = client.get(audio_key(job_id))
    if not audio:
        raise HTTPException(status_code=404, detail=f"音频结果已过期: {job_id}")
    return audio


def get_group_detail(group_id: str) -> dict[str, str | list[str] | None]:
    client = get_redis_client()
    raw = client.hgetall(group_key(group_id))
    if not raw:
        raise HTTPException(status_code=404, detail=f"任务组不存在或已过期: {group_id}")
    info = hash_to_text_map(raw)
    job_ids = [jid for jid in info.get("job_ids", "").split(",") if jid]
    return {
        "group_id": group_id,
        "status": info.get("status", QueueStatus.UNKNOWN.value),
        "request_id": info.get("request_id"),
        "total_segments": info.get("total"),
        "done_count": info.get("done_count"),
        "job_ids": job_ids,
        "created_at": info.get("created_at"),
        "updated_at": info.get("updated_at"),
        "error": info.get("error"),
    }


def get_group_audio_content(group_id: str) -> bytes:
    client = get_redis_client()
    raw = client.hgetall(group_key(group_id))
    if not raw:
        raise HTTPException(status_code=404, detail=f"任务组不存在或已过期: {group_id}")
    info = hash_to_text_map(raw)
    status = info.get("status")
    if status != QueueStatus.DONE.value:
        raise HTTPException(status_code=409, detail=f"任务组尚未完成: {status}（已完成 {info.get('done_count')}/{info.get('total')} 段）")
    audio = client.get(group_audio_key(group_id))
    if not audio:
        raise HTTPException(status_code=404, detail=f"合并音频已过期: {group_id}")
    return audio


def get_request_detail(request_id: str) -> dict[str, str | list[str] | None]:
    client = get_redis_client()
    info = _read_hash_text(client, request_key(request_id))
    if not info:
        raise HTTPException(status_code=404, detail=f"请求不存在或已过期: {request_id}")
    info = _refresh_request_state(client, request_id, info)
    return {
        "request_id": request_id,
        "status": info.get("status", QueueStatus.UNKNOWN.value),
        "request_type": info.get("request_type"),
        "client_request_id": info.get("client_request_id"),
        "job_id": info.get("job_id"),
        "group_id": info.get("group_id"),
        "created_at": info.get("created_at"),
        "updated_at": info.get("updated_at"),
        "error": info.get("error"),
    }


def _fetch_request_audio_bytes(client, info: dict[str, str], request_id: str) -> bytes:
    group_id = info.get("group_id")
    if group_id:
        audio = client.get(group_audio_key(group_id))
        if not audio:
            raise HTTPException(status_code=404, detail=f"合并音频已过期: {group_id}")
        return audio

    job_id = info.get("job_id")
    if not job_id:
        raise HTTPException(status_code=500, detail=f"请求缺少任务句柄: {request_id}")
    audio = client.get(audio_key(job_id))
    if not audio:
        raise HTTPException(status_code=404, detail=f"音频结果已过期: {job_id}")
    return audio


def get_request_audio_content(request_id: str) -> bytes:
    client = get_redis_client()
    info = _read_hash_text(client, request_key(request_id))
    if not info:
        raise HTTPException(status_code=404, detail=f"请求不存在或已过期: {request_id}")
    info = _refresh_request_state(client, request_id, info)
    status = info.get("status")
    if status != QueueStatus.DONE.value:
        raise HTTPException(status_code=409, detail=f"请求尚未完成: {status}")
    return _fetch_request_audio_bytes(client, info, request_id)


async def wait_for_request_audio_content(request_id: str, wait_timeout_seconds: int) -> bytes:
    """长轮询：阻塞直至音频就绪或超时（推荐替代 status + audio 双端点轮询）。"""
    deadline = time.time() + wait_timeout_seconds
    last_status = QueueStatus.UNKNOWN.value
    while time.time() < deadline:
        client = get_redis_client()
        info = _read_hash_text(client, request_key(request_id))
        if not info:
            raise HTTPException(status_code=404, detail=f"请求不存在或已过期: {request_id}")
        info = _refresh_request_state(client, request_id, info)
        last_status = info.get("status", QueueStatus.UNKNOWN.value)
        if last_status == QueueStatus.DONE.value:
            return _fetch_request_audio_bytes(client, info, request_id)
        if last_status == QueueStatus.FAILED.value:
            raise HTTPException(
                status_code=500,
                detail=f"TTS 任务失败: {info.get('error', 'unknown error')}",
            )
        await asyncio.sleep(WAIT_POLL_INTERVAL_SECONDS)

    raise HTTPException(
        status_code=504,
        detail={
            "request_id": request_id,
            "status": last_status,
            "message": f"等待超时（{wait_timeout_seconds}s），请增大 wait_timeout_seconds 后重试",
        },
    )

