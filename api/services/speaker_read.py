from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request

from api.schemas import SpeakersListResponse
from api.services import voices as voice_service
from api.utils.audio import file_response_for_speaker, resolve_speaker_audio_file, with_audio_url
from api.voice_context import get_voice_context

logger = logging.getLogger("indextts2-api")


def list_speakers(
    request: Request,
    *,
    language: Optional[str] = None,
    gender: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "voice_id",
    sort_order: str = "asc",
    page: int = 1,
    page_size: int = 50,
) -> SpeakersListResponse:
    voice_session_factory, prompt_dir = get_voice_context()
    try:
        if not os.path.exists(prompt_dir):
            return SpeakersListResponse(
                voices=[],
                speakers=[],
                count=0,
                directory=prompt_dir,
                message="提示音频目录不存在",
            )
        voices, total = voice_service.list_voices_from_db(
            voice_session_factory,
            prompt_dir,
            language=language,
            gender=gender,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )
        voices_out = [with_audio_url(request, v) for v in voices]
        return SpeakersListResponse(
            voices=voices_out,
            speakers=[v.voice_id for v in voices_out],
            count=total,
            directory=prompt_dir,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error("Error getting speakers: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


def download_speaker_audio(voice_id: str):
    if not voice_id or voice_id != Path(voice_id).name:
        raise HTTPException(status_code=404, detail="speaker 不存在")
    voice_session_factory, prompt_dir = get_voice_context()
    try:
        voice = voice_service.get_voice_by_id(voice_session_factory, prompt_dir, voice_id)
        if voice is None:
            raise HTTPException(status_code=404, detail="speaker 不存在")
        path = resolve_speaker_audio_file(prompt_dir, voice)
        if path is None:
            raise HTTPException(status_code=404, detail="音频文件不存在")
        return file_response_for_speaker(path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error serving speaker audio %s: %s", voice_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
