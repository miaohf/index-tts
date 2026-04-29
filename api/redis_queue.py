from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import redis

DEFAULT_JOB_QUEUE_NAME = "indextts:tts:jobs"
DEFAULT_REQUEST_QUEUE_NAME = "indextts:tts:requests"
DEFAULT_CLIENT_REQUEST_PREFIX = "indextts:tts:clientreq:"
DEFAULT_JOB_TTL_SECONDS = 1800
DEFAULT_MAX_REQUEST_SIZE = 200


def now_ts() -> int:
    return int(time.time())


def get_redis_client(redis_url: str | None = None) -> redis.Redis:
    url = redis_url or os.getenv("INDEX_TTS_REDIS_URL", "redis://127.0.0.1:6379/0")
    return redis.Redis.from_url(url, decode_responses=False)


def queue_name() -> str:
    return os.getenv("INDEX_TTS_QUEUE_NAME", DEFAULT_JOB_QUEUE_NAME)


def request_queue_name() -> str:
    return os.getenv("INDEX_TTS_REQUEST_QUEUE_NAME", DEFAULT_REQUEST_QUEUE_NAME)


def max_queue_size() -> int:
    # 兼容旧逻辑：历史上以“队列上限”限制入队。
    # 现已改为“请求上限”，此函数仅保留给旧代码/旧接口字段使用。
    return max_request_size()


def max_request_size() -> int:
    value = os.getenv("INDEX_TTS_MAX_REQUEST_SIZE")
    if not value:
        # 向后兼容旧环境变量
        value = os.getenv("INDEX_TTS_MAX_QUEUE_SIZE")
    if not value:
        return DEFAULT_MAX_REQUEST_SIZE
    try:
        return max(1, int(value))
    except ValueError:
        return DEFAULT_MAX_REQUEST_SIZE


def job_ttl_seconds() -> int:
    value = os.getenv("INDEX_TTS_JOB_TTL_SECONDS")
    if not value:
        return DEFAULT_JOB_TTL_SECONDS
    try:
        return max(60, int(value))
    except ValueError:
        return DEFAULT_JOB_TTL_SECONDS


def new_job_id() -> str:
    return uuid.uuid4().hex


def job_key(job_id: str) -> str:
    return f"indextts:tts:job:{job_id}"


def request_key(request_id: str) -> str:
    return f"indextts:tts:request:{request_id}"


def client_request_key(client_request_id: str) -> str:
    return f"{DEFAULT_CLIENT_REQUEST_PREFIX}{client_request_id}"


def audio_key(job_id: str) -> str:
    return f"indextts:tts:audio:{job_id}"


def group_key(group_id: str) -> str:
    return f"indextts:tts:group:{group_id}"


def group_audio_key(group_id: str) -> str:
    return f"indextts:tts:group:audio:{group_id}"


def encode_job_message(job_id: str, request_type: str, payload: dict[str, Any]) -> bytes:
    body = {
        "job_id": job_id,
        "request_type": request_type,
        "payload": payload,
        "created_at": now_ts(),
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def decode_job_message(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


def bytes_to_text(data: bytes | None) -> str | None:
    if data is None:
        return None
    return data.decode("utf-8")


def hash_to_text_map(raw_map: dict[bytes, bytes]) -> dict[str, str]:
    return {k.decode("utf-8"): v.decode("utf-8") for k, v in raw_map.items()}
