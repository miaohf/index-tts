from __future__ import annotations

from fastapi import HTTPException

from api.redis_queue import (
    audio_key,
    get_redis_client,
    group_audio_key,
    group_key,
    hash_to_text_map,
    job_key,
    request_key,
)
from api.services.queue_status import QueueStatus


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
    raw = client.hgetall(request_key(request_id))
    if not raw:
        raise HTTPException(status_code=404, detail=f"请求不存在或已过期: {request_id}")
    info = hash_to_text_map(raw)
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


def get_request_audio_content(request_id: str) -> bytes:
    client = get_redis_client()
    raw = client.hgetall(request_key(request_id))
    if not raw:
        raise HTTPException(status_code=404, detail=f"请求不存在或已过期: {request_id}")
    info = hash_to_text_map(raw)
    status = info.get("status")
    if status != QueueStatus.DONE.value:
        raise HTTPException(status_code=409, detail=f"请求尚未完成: {status}")

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

