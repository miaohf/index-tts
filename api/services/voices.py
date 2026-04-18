from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from api.config import VOICE_SORT_FIELDS
from api.database.models import Voice, VoiceLabel, VoiceStat
from api.schemas import VoiceInfo, VoiceUpdateRequest


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _split_lang_gender_from_labels(
    labels: Optional[Dict[str, str]],
    language: Optional[str],
    gender: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[Dict[str, str]]]:
    if not labels:
        return language, gender, labels
    m = {str(k): str(v) for k, v in labels.items()}
    if language is None:
        language = m.pop("language", None)
    else:
        m.pop("language", None)
    if gender is None:
        gender = m.pop("gender", None) or m.pop("sex", None)
    else:
        m.pop("gender", None)
        m.pop("sex", None)
    return language, gender, m if m else None


def _voice_by_business_id(session: Session, voice_id: str) -> Voice | None:
    """按业务主键 `voice_id` 查询（表主键为自增 `id`）。"""
    return session.scalar(select(Voice).where(Voice.voice_id == voice_id))


def _fetch_voice_labels_map(session: Session, voice_ids: List[str]) -> Dict[str, Dict[str, str]]:
    if not voice_ids:
        return {}
    rows = session.execute(
        select(VoiceLabel).where(VoiceLabel.voice_id.in_(voice_ids))
    ).scalars().all()
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        out.setdefault(row.voice_id, {})[row.key] = row.value
    return out


def _voice_to_info(
    v: Voice,
    labels: Dict[str, str],
    usage_count: int,
    last_used_at: Optional[str],
) -> VoiceInfo:
    lang = v.language or labels.get("language")
    gen = v.gender or labels.get("gender") or labels.get("sex")
    return VoiceInfo(
        id=v.id,
        voice_id=v.voice_id,
        name=v.name,
        description=v.description or "",
        category=v.category,
        language=lang,
        gender=gen,
        file_name=v.file_name,
        enabled=bool(v.enabled),
        owner=v.owner,
        version=v.version,
        created_at=v.created_at,
        updated_at=v.updated_at,
        usage_count=usage_count,
        last_used_at=last_used_at,
    )


def sync_files_to_voice_db(session_factory: sessionmaker[Session], prompt_dir: str) -> None:
    if not os.path.exists(prompt_dir):
        return
    now = _utc_now_iso()
    files = [f for f in os.listdir(prompt_dir) if f.lower().endswith((".wav", ".mp3"))]
    with session_factory() as session:
        with session.begin():
            for file_name in files:
                voice_id = os.path.splitext(file_name)[0]
                v = _voice_by_business_id(session, voice_id)
                if v is None:
                    session.add(
                        Voice(
                            voice_id=voice_id,
                            name=voice_id,
                            description="",
                            file_name=file_name,
                            enabled=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    v.file_name = file_name
                    v.updated_at = now
                st = session.get(VoiceStat, voice_id)
                if st is None:
                    session.add(VoiceStat(voice_id=voice_id))


def list_voices_from_db(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    *,
    language: Optional[str] = None,
    gender: Optional[str] = None,
    category: Optional[str] = None,
    enabled: Optional[bool] = None,
    search: Optional[str] = None,
    label_key: Optional[str] = None,
    label_value: Optional[str] = None,
    sort_by: str = "voice_id",
    sort_order: str = "asc",
    page: int = 1,
    page_size: int = 50,
) -> tuple[List[VoiceInfo], int]:
    del prompt_dir  # 保留签名与旧调用一致
    sort_key = VOICE_SORT_FIELDS.get(sort_by, "voice_id")
    desc = sort_order.lower() == "desc"

    filters: List[Any] = []
    if category:
        filters.append(Voice.category == category)
    if enabled is not None:
        filters.append(Voice.enabled == enabled)
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
    if label_key:
        vl = VoiceLabel
        if label_value is not None:
            filters.append(
                exists().where(
                    vl.voice_id == Voice.voice_id,
                    vl.key == label_key,
                    vl.value == label_value,
                )
            )
        else:
            filters.append(exists().where(vl.voice_id == Voice.voice_id, vl.key == label_key))

    base_from = Voice.__table__.outerjoin(
        VoiceStat.__table__, VoiceStat.voice_id == Voice.voice_id
    )

    count_stmt = select(func.count()).select_from(base_from)
    if filters:
        count_stmt = count_stmt.where(*filters)

    if sort_key == "usage_count":
        order_col = func.coalesce(VoiceStat.request_count, 0)
    else:
        order_col = getattr(Voice, sort_key, Voice.voice_id)
    order_expr = order_col.desc() if desc else order_col.asc()

    offset = (page - 1) * page_size
    list_stmt = (
        select(Voice, func.coalesce(VoiceStat.request_count, 0), VoiceStat.last_used_at)
        .outerjoin(VoiceStat, VoiceStat.voice_id == Voice.voice_id)
        .order_by(order_expr)
        .limit(page_size)
        .offset(offset)
    )
    if filters:
        list_stmt = list_stmt.where(*filters)

    with session_factory() as session:
        total = int(session.execute(count_stmt).scalar_one())
        rows = session.execute(list_stmt).all()
        voice_ids = [r[0].voice_id for r in rows]
        labels_map = _fetch_voice_labels_map(session, voice_ids)
        voices = [
            _voice_to_info(
                r[0],
                labels_map.get(r[0].voice_id, {}),
                int(r[1] or 0),
                r[2],
            )
            for r in rows
        ]
    return voices, total


def get_voice_by_id(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    voice_id: str,
) -> Optional[VoiceInfo]:
    del prompt_dir
    with session_factory() as session:
        row = session.execute(
            select(Voice, func.coalesce(VoiceStat.request_count, 0), VoiceStat.last_used_at)
            .outerjoin(VoiceStat, VoiceStat.voice_id == Voice.voice_id)
            .where(Voice.voice_id == voice_id)
        ).first()
        if row is None:
            return None
        v, usage_count, last_used_at = row[0], row[1], row[2]
        labels = _fetch_voice_labels_map(session, [voice_id]).get(voice_id, {})
        return _voice_to_info(v, labels, int(usage_count or 0), last_used_at)


def upsert_voice(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    *,
    voice_id: str,
    file_name: str,
    name: Optional[str] = None,
    description: str = "",
    category: Optional[str] = None,
    language: Optional[str] = None,
    gender: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
    owner: Optional[str] = None,
    version: Optional[str] = None,
    enabled: bool = True,
) -> None:
    del prompt_dir
    language, gender, labels = _split_lang_gender_from_labels(labels, language, gender)
    now = _utc_now_iso()
    with session_factory() as session:
        with session.begin():
            v = _voice_by_business_id(session, voice_id)
            if v is None:
                v = Voice(
                    voice_id=voice_id,
                    name=name or voice_id,
                    description=description,
                    category=category,
                    language=language,
                    gender=gender,
                    file_name=file_name,
                    enabled=enabled,
                    owner=owner,
                    version=version,
                    created_at=now,
                    updated_at=now,
                )
                session.add(v)
            else:
                v.name = name or voice_id
                v.description = description
                v.category = category
                v.language = language
                v.gender = gender
                v.file_name = file_name
                v.enabled = enabled
                v.owner = owner
                v.version = version
                v.updated_at = now
            st = session.get(VoiceStat, voice_id)
            if st is None:
                session.add(VoiceStat(voice_id=voice_id))
            if labels is not None:
                session.execute(delete(VoiceLabel).where(VoiceLabel.voice_id == voice_id))
                for k, val in labels.items():
                    session.add(VoiceLabel(voice_id=voice_id, key=str(k), value=str(val)))


def update_voice(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    voice_id: str,
    req: VoiceUpdateRequest,
) -> bool:
    del prompt_dir
    lang_val, gen_val, labels_to_store = _split_lang_gender_from_labels(
        req.labels, req.language, req.gender
    )
    now = _utc_now_iso()
    with session_factory() as session:
        # 须在 begin 之前不要先 get：否则 autobegin 后再 session.begin() 会报
        # "A transaction is already begun on this Session."
        with session.begin():
            v = _voice_by_business_id(session, voice_id)
            if v is None:
                return False
            if req.name is not None:
                v.name = req.name
            if req.description is not None:
                v.description = req.description
            if req.category is not None:
                v.category = req.category
            if req.enabled is not None:
                v.enabled = req.enabled
            if req.owner is not None:
                v.owner = req.owner
            if req.version is not None:
                v.version = req.version
            if req.language is not None:
                v.language = req.language
            elif lang_val is not None:
                v.language = lang_val
            if req.gender is not None:
                v.gender = req.gender
            elif gen_val is not None:
                v.gender = gen_val
            v.updated_at = now
            if req.labels is not None:
                session.execute(delete(VoiceLabel).where(VoiceLabel.voice_id == voice_id))
                if labels_to_store:
                    for k, val in labels_to_store.items():
                        session.add(
                            VoiceLabel(voice_id=voice_id, key=str(k), value=str(val))
                        )
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
            st = session.get(VoiceStat, voice_id)
            if st is None:
                session.add(
                    VoiceStat(
                        voice_id=voice_id,
                        request_count=1,
                        total_audio_seconds=sec,
                        last_used_at=now,
                    )
                )
            else:
                st.request_count = int(st.request_count or 0) + 1
                st.total_audio_seconds = float(st.total_audio_seconds or 0.0) + sec
                st.last_used_at = now


def resolve_voice_prompt_path(
    session_factory: sessionmaker[Session],
    prompt_dir: str,
    speaker: str,
) -> Optional[str]:
    voice = get_voice_by_id(session_factory, prompt_dir, speaker)
    if voice is None:
        return None
    if not voice.enabled:
        raise ValueError(f"speaker '{speaker}' 已被禁用")
    path = os.path.join(prompt_dir, voice.file_name)
    if not os.path.isfile(path):
        raise ValueError(f"speaker '{speaker}' 的音频文件不存在: {voice.file_name}")
    return path
