from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from api.schemas import OpenAIVoice, OpenAIVoiceListResponse, VoiceCreateRequest, VoiceInfo, VoiceUpdateRequest
from api.services import voices as voice_store
from api.services.voice_write import (
    create_voice,
    update_voice,
    upload_voice_audio,
    validate_voice_id,
)
from api.utils.audio import voice_audio_path, voice_audio_url
from api.voice_context import get_voice_context


def _iso_to_unix(iso: Optional[str]) -> int:
    if not iso or not str(iso).strip():
        return 0
    text = str(iso).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _slug_voice_id(name: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name.strip(), flags=re.UNICODE)
    slug = slug.strip("_")
    if not slug:
        raise HTTPException(status_code=400, detail="name 无法生成有效的 voice id")
    return slug


def voice_info_to_openai(request: Request, voice: VoiceInfo) -> OpenAIVoice:
    return OpenAIVoice(
        id=voice.voice_id,
        name=voice.name,
        created_at=_iso_to_unix(voice.created_at),
        description=voice.description or "",
        language=voice.language,
        gender=voice.gender,
        preview_url=voice_audio_url(request, voice.voice_id),
        preview_path=voice_audio_path(voice.voice_id),
        request_count=voice.request_count,
        total_audio_seconds=voice.total_audio_seconds,
        last_used_at=voice.last_used_at,
        updated_at=_iso_to_unix(voice.updated_at) or None,
    )


def list_openai_voices(
    request: Request,
    *,
    language: Optional[str] = None,
    gender: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "voice_id",
    sort_order: str = "asc",
    limit: int = 20,
    after: Optional[str] = None,
) -> OpenAIVoiceListResponse:
    voice_session_factory, prompt_dir = get_voice_context()
    all_voices, _total = voice_store.list_voices_from_db(
        voice_session_factory,
        prompt_dir,
        language=language,
        gender=gender,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=1,
        page_size=10_000,
    )

    start = 0
    if after:
        ids = [v.voice_id for v in all_voices]
        if after in ids:
            start = ids.index(after) + 1

    page_voices = all_voices[start : start + limit]
    data = [voice_info_to_openai(request, v) for v in page_voices]
    return OpenAIVoiceListResponse(
        data=data,
        has_more=start + limit < len(all_voices),
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


def get_openai_voice(request: Request, voice_id: str) -> OpenAIVoice:
    voice_session_factory, prompt_dir = get_voice_context()
    voice = voice_store.get_voice_by_id(voice_session_factory, prompt_dir, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail=f"voice '{voice_id}' 不存在")
    return voice_info_to_openai(request, voice)


async def create_openai_voice(
    request: Request,
    *,
    name: str,
    audio_sample,
    voice_id: Optional[str] = None,
    description: str = "",
    language: Optional[str] = None,
    gender: Optional[str] = None,
) -> OpenAIVoice:
    vid = validate_voice_id(voice_id or _slug_voice_id(name))
    if not language or not gender:
        raise HTTPException(status_code=400, detail="language 与 gender 为必填")
    await upload_voice_audio(
        source_file=audio_sample,
        voice_id=vid,
        name=name.strip() or vid,
        description=description,
        language=language,
        gender=gender,
    )
    return get_openai_voice(request, vid)


def create_openai_voice_metadata(request: Request, body: VoiceCreateRequest) -> OpenAIVoice:
    voice = create_voice(body, request)
    return voice_info_to_openai(request, voice)


def update_openai_voice(request: Request, voice_id: str, body: VoiceUpdateRequest) -> OpenAIVoice:
    voice = update_voice(voice_id, body, request)
    return voice_info_to_openai(request, voice)
