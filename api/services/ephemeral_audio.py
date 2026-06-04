"""临时参考音（视频翻译分片）：仅落盘，不入库，TTL 到期自动清理。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, UploadFile

from api.config import (
    SESSION_META_FILENAME,
    ephemeral_cleanup_interval_seconds,
    ephemeral_ttl_seconds,
    max_upload_bytes,
    resolve_ephemeral_dir,
)
from api.schemas import UploadRefAudioResponse
from api.utils.ref_audio_path import (
    build_ephemeral_ref_path,
    sanitize_basename,
    validate_audio_extension,
    validate_session_id,
)

logger = logging.getLogger("indextts2-api")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_expires_at(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_expires_at(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _session_dir(ephemeral_dir: str, session_id: str) -> str:
    return os.path.join(ephemeral_dir, session_id)


def _session_meta_path(ephemeral_dir: str, session_id: str) -> str:
    return os.path.join(_session_dir(ephemeral_dir, session_id), SESSION_META_FILENAME)


def _write_session_meta(ephemeral_dir: str, session_id: str, expires_at: datetime) -> None:
    meta_path = _session_meta_path(ephemeral_dir, session_id)
    payload = {
        "session_id": session_id,
        "expires_at": _format_expires_at(expires_at),
        "updated_at": _format_expires_at(_utc_now()),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def touch_session_expiry(ephemeral_dir: str, session_id: str) -> None:
    """上传或 TTS 引用时刷新 session 过期时间（滑动 TTL）。"""
    session_path = _session_dir(ephemeral_dir, session_id)
    if not os.path.isdir(session_path):
        return
    expires_at = _utc_now() + timedelta(seconds=ephemeral_ttl_seconds())
    _write_session_meta(ephemeral_dir, session_id, expires_at)


def cleanup_expired_sessions() -> int:
    """扫描 ephemeral 目录，删除已过期的 session。返回删除的 session 数。"""
    ephemeral_dir = resolve_ephemeral_dir()
    if not os.path.isdir(ephemeral_dir):
        return 0

    now = _utc_now()
    removed = 0
    ttl = ephemeral_ttl_seconds()

    for entry in os.scandir(ephemeral_dir):
        if not entry.is_dir():
            continue
        session_id = entry.name
        meta_path = os.path.join(entry.path, SESSION_META_FILENAME)
        should_remove = False

        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                expires_at = _parse_expires_at(meta["expires_at"])
                should_remove = expires_at <= now
            except (OSError, KeyError, ValueError, TypeError) as e:
                logger.warning("Failed to read session metadata %s: %s", meta_path, e)
                should_remove = (now - datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc)).total_seconds() > ttl
        else:
            should_remove = (now - datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc)).total_seconds() > ttl

        if should_remove:
            try:
                shutil.rmtree(entry.path)
                removed += 1
                logger.info("Removed expired ephemeral session: %s", session_id)
            except OSError as e:
                logger.warning("Failed to remove ephemeral session %s: %s", session_id, e)

    return removed


async def run_cleanup_loop() -> None:
    interval = ephemeral_cleanup_interval_seconds()
    logger.info(
        "Ephemeral ref-audio TTL cleanup started: interval=%ds, ttl=%ds, dir=%s",
        interval,
        ephemeral_ttl_seconds(),
        resolve_ephemeral_dir(),
    )
    while True:
        try:
            removed = await asyncio.to_thread(cleanup_expired_sessions)
            if removed:
                logger.info("TTL cleanup finished, removed %d session(s)", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ephemeral ref-audio TTL cleanup failed")
        await asyncio.sleep(interval)


async def upload_ephemeral_ref(
    *,
    session_id: str,
    source_file: UploadFile,
    segment_id: Optional[str] = None,
) -> UploadRefAudioResponse:
    ephemeral_dir = resolve_ephemeral_dir()
    try:
        sid = validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not source_file.filename:
        raise HTTPException(status_code=400, detail="未上传音频文件")

    try:
        if segment_id and segment_id.strip():
            filename = sanitize_basename(segment_id.strip())
        else:
            filename = sanitize_basename(source_file.filename)
        validate_audio_extension(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    session_path = _session_dir(ephemeral_dir, sid)
    os.makedirs(session_path, exist_ok=True)
    save_path = os.path.join(session_path, filename)

    content = await source_file.read()
    limit = max_upload_bytes()
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，最大允许 {limit // (1024 * 1024)} MB",
        )

    with open(save_path, "wb") as f:
        f.write(content)

    expires_at = _utc_now() + timedelta(seconds=ephemeral_ttl_seconds())
    _write_session_meta(ephemeral_dir, sid, expires_at)

    ref_path = build_ephemeral_ref_path(sid, filename)
    logger.info("Ephemeral ref-audio saved: session=%s file=%s", sid, save_path)

    return UploadRefAudioResponse(
        status="success",
        message="临时参考音上传成功",
        session_id=sid,
        segment_id=filename,
        ref_path=ref_path,
        file_path=save_path,
        expires_at=_format_expires_at(expires_at),
    )
