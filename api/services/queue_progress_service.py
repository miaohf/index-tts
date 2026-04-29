from __future__ import annotations

from collections import Counter
from typing import Any

from api.redis_queue import (
    get_redis_client,
    hash_to_text_map,
    job_ttl_seconds,
    max_request_size,
    queue_name,
    request_queue_name,
)
from api.services.queue_submit_service import AUTO_SPLIT_SEGMENT_LENGTH, AUTO_SPLIT_THRESHOLD
from api.services.queue_status import QueueStatus


def _to_int(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def get_queue_status() -> dict[str, int | str]:
    client = get_redis_client()
    q_name = queue_name()
    rq_name = request_queue_name()
    request_cap = max_request_size()
    request_status_counts = _collect_request_status_counts(client)
    return {
        "queue_name": q_name,
        "queue_depth": int(client.llen(q_name)),
        "request_queue_name": rq_name,
        "request_queue_depth": int(client.zcard(rq_name)),
        "request_capacity": request_cap,
        "queue_capacity": request_cap,  # 兼容旧字段，含义已变为请求上限
        "active_requests": request_status_counts[QueueStatus.QUEUED.value] + request_status_counts[QueueStatus.PROCESSING.value],
        "request_status_counts": dict(request_status_counts),
        "job_ttl_seconds": job_ttl_seconds(),
        "auto_split_threshold": AUTO_SPLIT_THRESHOLD,
        "auto_split_segment_length": AUTO_SPLIT_SEGMENT_LENGTH,
    }


def _collect_request_status_counts(client: Any) -> Counter[str]:
    request_status_counts: Counter[str] = Counter()
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match="indextts:tts:request:*", count=300)
        for key in keys:
            raw = client.hgetall(key)
            if not raw:
                continue
            info = hash_to_text_map(raw)
            status = info.get("status", QueueStatus.UNKNOWN.value)
            request_status_counts[status] += 1
        if cursor == 0:
            break
    return request_status_counts


def get_queue_progress(include_groups: bool, max_group_items: int) -> dict[str, Any]:
    client = get_redis_client()
    q_name = queue_name()
    rq_name = request_queue_name()
    request_cap = max_request_size()
    request_status_counts = _collect_request_status_counts(client)

    status_counter: Counter[str] = Counter()
    processing_by_gpu: Counter[str] = Counter()
    group_job_status_counter: dict[str, Counter[str]] = {}
    group_job_total_segments: dict[str, int] = {}
    group_job_updated_at: dict[str, int] = {}
    total_jobs = 0

    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match="indextts:tts:job:*", count=500)
        for key in keys:
            raw = client.hgetall(key)
            if not raw:
                continue
            info = hash_to_text_map(raw)
            total_jobs += 1
            status = info.get("status", QueueStatus.UNKNOWN.value)
            status_counter[status] += 1
            if status == QueueStatus.PROCESSING.value:
                gpu = info.get("worker_gpu", QueueStatus.UNKNOWN.value)
                processing_by_gpu[gpu] += 1

            group_id = info.get("group_id")
            if group_id:
                if group_id not in group_job_status_counter:
                    group_job_status_counter[group_id] = Counter()
                group_job_status_counter[group_id][status] += 1

                seg_total = _to_int(info.get("total_segments"))
                if seg_total > 0:
                    group_job_total_segments[group_id] = max(group_job_total_segments.get(group_id, 0), seg_total)

                updated_at = _to_int(info.get("updated_at"))
                if updated_at > 0:
                    group_job_updated_at[group_id] = max(group_job_updated_at.get(group_id, 0), updated_at)
        if cursor == 0:
            break

    payload: dict[str, Any] = {
        "queue_name": q_name,
        "queue_depth": int(client.llen(q_name)),
        "request_queue_name": rq_name,
        "request_queue_depth": int(client.zcard(rq_name)),
        "request_capacity": request_cap,
        "queue_capacity": request_cap,  # 兼容旧字段，含义已变为请求上限
        "active_requests": request_status_counts[QueueStatus.QUEUED.value] + request_status_counts[QueueStatus.PROCESSING.value],
        "request_status_counts": dict(request_status_counts),
        "job_ttl_seconds": job_ttl_seconds(),
        "total_job_hashes": total_jobs,
        "job_status_counts": dict(status_counter),
        "processing_by_gpu": dict(processing_by_gpu),
        "auto_split_threshold": AUTO_SPLIT_THRESHOLD,
        "auto_split_segment_length": AUTO_SPLIT_SEGMENT_LENGTH,
    }

    if not include_groups:
        return payload

    groups: list[dict[str, Any]] = []
    group_status_counter: Counter[str] = Counter()
    group_cursor = 0
    while True:
        group_cursor, group_keys = client.scan(group_cursor, match="indextts:tts:group:*", count=200)
        for key in group_keys:
            if b":audio:" in key:
                continue
            raw = client.hgetall(key)
            if not raw:
                continue
            info = hash_to_text_map(raw)
            group_id = key.decode("utf-8").rsplit(":", 1)[-1]
            calc = group_job_status_counter.get(group_id, Counter())

            queued_count = calc.get(QueueStatus.QUEUED.value, 0)
            processing_count = calc.get(QueueStatus.PROCESSING.value, 0)
            done_count = calc.get(QueueStatus.DONE.value, 0)
            failed_count = calc.get(QueueStatus.FAILED.value, 0)
            unknown_count = sum(
                count
                for status, count in calc.items()
                if status not in {
                    QueueStatus.QUEUED.value,
                    QueueStatus.PROCESSING.value,
                    QueueStatus.DONE.value,
                    QueueStatus.FAILED.value,
                }
            )

            total = _to_int(info.get("total"))
            if total <= 0:
                total = group_job_total_segments.get(group_id, 0)
            if total <= 0:
                total = queued_count + processing_count + done_count + failed_count + unknown_count

            if failed_count > 0:
                group_status = QueueStatus.FAILED.value
            elif total > 0 and done_count >= total:
                group_status = QueueStatus.DONE.value
            elif processing_count > 0:
                group_status = QueueStatus.PROCESSING.value
            elif queued_count > 0:
                group_status = QueueStatus.QUEUED.value
            else:
                group_status = info.get("status", QueueStatus.UNKNOWN.value)

            updated_at = max(_to_int(info.get("updated_at")), group_job_updated_at.get(group_id, 0))
            group_status_counter[group_status] += 1
            groups.append(
                {
                    "group_id": group_id,
                    "status": group_status,
                    "queued_count": queued_count,
                    "processing_count": processing_count,
                    "failed_count": failed_count,
                    "unknown_count": unknown_count,
                    "done_count": done_count,
                    "total_segments": total,
                    "progress": (round(done_count / total, 4) if total > 0 else 0.0),
                    "updated_at": str(updated_at) if updated_at else info.get("updated_at"),
                    "created_at": info.get("created_at"),
                }
            )
        if group_cursor == 0:
            break

    groups.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    payload["groups_total"] = len(groups)
    payload["group_status_counts"] = dict(group_status_counter)
    payload["groups"] = groups[:max_group_items]
    return payload

