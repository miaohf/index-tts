from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from api.config import VOICE_SORT_FIELDS
from api.database.models import Voice
from api.schemas import VoiceInfo, VoiceUpdateRequest


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _voice_by_business_id(session: Session, voice_id: str) -> Voice | None:
    return session.scalar(select(Voice).where(Voice.voice_id == voice_id))


def _voice_to_info(v: Voice) -> VoiceInfo:
    return VoiceInfo(
        id=v.id,
        voice_id=v.voice_id,
        name=v.name,
        description=v.description or "",
        language=v.language,
        gender=v.gender,
        file_name=v.file_name,
        request_count=int(v.request_count or 0),
        total_audio_seconds=float(v.total_audio_seconds or 0.0),
        last_used_at=v.last_used_at,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def list_voices_from_db(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    *,
    language: Optional[str] = None,
    gender: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "voice_id",
    sort_order: str = "asc",
    page: int = 1,
    page_size: int = 50,
) -> tuple[List[VoiceInfo], int]:
    del prompt_dir
    sort_key = VOICE_SORT_FIELDS.get(sort_by, "voice_id")
    desc = sort_order.lower() == "desc"

    filters: List[Any] = []
    if search:
        like = f"%{search}%"
        filters.append(
            or_(
                Voice.voice_id.like(like),
                Voice.name.like(like),
                Voice.description.like(like),
                func.coalesce(Voice.language, "").like(like),
                func.coalesce(Voice.gender, "").like(like),
            )
        )
    if language:
        filters.append(Voice.language == language)
    if gender:
        filters.append(Voice.gender == gender)

    count_stmt = select(func.count()).select_from(Voice)
    if filters:
        count_stmt = count_stmt.where(*filters)

    order_col = getattr(Voice, sort_key, Voice.voice_id)
    order_expr = order_col.desc() if desc else order_col.asc()
    offset = (page - 1) * page_size
    list_stmt = select(Voice).order_by(order_expr).limit(page_size).offset(offset)
    if filters:
        list_stmt = list_stmt.where(*filters)

    with session_factory() as session:
        total = int(session.execute(count_stmt).scalar_one())
        rows = session.execute(list_stmt).scalars().all()
        return [_voice_to_info(v) for v in rows], total


def get_voice_by_id(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    voice_id: str,
) -> Optional[VoiceInfo]:
    del prompt_dir
    with session_factory() as session:
        v = _voice_by_business_id(session, voice_id)
        return _voice_to_info(v) if v else None


def get_voice_by_file_name(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    file_name: str,
) -> Optional[VoiceInfo]:
    del prompt_dir
    with session_factory() as session:
        v = session.scalar(
            select(Voice)
            .where(Voice.file_name == file_name)
            .order_by(Voice.updated_at.desc(), Voice.id.desc())
        )
        return _voice_to_info(v) if v else None


def upsert_voice(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    *,
    voice_id: str,
    file_name: str,
    name: Optional[str] = None,
    description: str = "",
    language: Optional[str] = None,
    gender: Optional[str] = None,
) -> None:
    del prompt_dir
    now = _utc_now_iso()
    with session_factory() as session:
        with session.begin():
            v = _voice_by_business_id(session, voice_id)
            if v is None:
                session.add(
                    Voice(
                        voice_id=voice_id,
                        name=name or voice_id,
                        description=description,
                        language=language,
                        gender=gender,
                        file_name=file_name,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                v.name = name or voice_id
                v.description = description
                v.language = language
                v.gender = gender
                v.file_name = file_name
                v.updated_at = now


def update_voice(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    voice_id: str,
    req: VoiceUpdateRequest,
) -> bool:
    del prompt_dir
    now = _utc_now_iso()
    with session_factory() as session:
        with session.begin():
            v = _voice_by_business_id(session, voice_id)
            if v is None:
                return False
            if req.name is not None:
                v.name = req.name
            if req.description is not None:
                v.description = req.description
            if req.language is not None:
                v.language = req.language
            if req.gender is not None:
                v.gender = req.gender
            if req.file_name is not None:
                v.file_name = req.file_name
            v.updated_at = now
    return True


def delete_voice(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    voice_id: str,
    *,
    remove_file: bool = False,
) -> bool:
    file_name: Optional[str] = None
    with session_factory() as session:
        with session.begin():
            v = _voice_by_business_id(session, voice_id)
            if v is None:
                return False
            file_name = v.file_name
            session.delete(v)
    if remove_file and file_name:
        path = os.path.join(prompt_dir, file_name)
        if os.path.isfile(path):
            os.remove(path)
    return True


def record_voice_usage(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    voice_id: str,
    audio_seconds: float,
) -> None:
    del prompt_dir
    now = _utc_now_iso()
    sec = max(audio_seconds, 0.0)
    with session_factory() as session:
        with session.begin():
            v = _voice_by_business_id(session, voice_id)
            if v is None:
                return
            v.request_count = int(v.request_count or 0) + 1
            v.total_audio_seconds = float(v.total_audio_seconds or 0.0) + sec
            v.last_used_at = now


def resolve_voice_prompt_path(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    voice_id: str,
) -> Optional[str]:
    voice = get_voice_by_id(session_factory, prompt_dir, voice_id)
    if voice is None:
        return None
    path = os.path.join(prompt_dir, voice.file_name)
    if not os.path.isfile(path):
        raise ValueError(f"voice '{voice_id}' 的音频文件不存在: {voice.file_name}")
    return path
