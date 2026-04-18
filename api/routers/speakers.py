import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from api.inference import model
from api.schemas import (
    SpeakersListResponse,
    VoiceCreateRequest,
    VoiceInfo,
    VoiceUpdateRequest,
)
from api.services import voices as voice_service
from api.utils.audio import file_response_for_speaker, resolve_speaker_audio_file, with_audio_url

logger = logging.getLogger("indextts2-api")

router = APIRouter(tags=["speakers"])


@router.get("/speakers/{voice_id}/audio", name="download_speaker_audio")
async def download_speaker_audio(voice_id: str):
    if not voice_id or voice_id != Path(voice_id).name:
        raise HTTPException(status_code=404, detail="speaker 不存在")
    try:
        voice = voice_service.get_voice_by_id(
            model.voice_session_factory, model.prompt_dir, voice_id
        )
        if voice is None:
            raise HTTPException(status_code=404, detail="speaker 不存在")
        path = resolve_speaker_audio_file(model.prompt_dir, voice)
        if path is None:
            raise HTTPException(status_code=404, detail="音频文件不存在")
        return file_response_for_speaker(path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving speaker audio {voice_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/speakers", response_model=SpeakersListResponse)
async def get_speakers(
    request: Request,
    language: Optional[str] = Query(default=None),
    gender: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    enabled: Optional[bool] = Query(default=True),
    search: Optional[str] = Query(default=None),
    label_key: Optional[str] = Query(default=None),
    label_value: Optional[str] = Query(default=None),
    sort_by: str = Query(default="voice_id"),
    sort_order: str = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """返回音色列表（SQLAlchemy），支持筛选、排序和分页。"""
    try:
        if not os.path.exists(model.prompt_dir):
            return SpeakersListResponse(
                voices=[],
                speakers=[],
                count=0,
                directory=model.prompt_dir,
                message="提示音频目录不存在",
            )
        voice_service.sync_files_to_voice_db(model.voice_session_factory, model.prompt_dir)
        voices, total = voice_service.list_voices_from_db(
            model.voice_session_factory,
            model.prompt_dir,
            language=language,
            gender=gender,
            category=category,
            enabled=enabled,
            search=search,
            label_key=label_key,
            label_value=label_value,
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
            directory=model.prompt_dir,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"Error getting speakers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/speakers", response_model=VoiceInfo, status_code=201)
async def create_speaker_metadata(body: VoiceCreateRequest, request: Request):
    """仅写入音色元数据，不要求磁盘上已有音频；file_name 默认 `{voice_id}.wav`，后续可用 /upload_audio（必填 voice_id 等）上传音频。"""
    file_name = body.file_name or f"{body.voice_id}.wav"
    try:
        voice_service.upsert_voice(
            model.voice_session_factory,
            model.prompt_dir,
            voice_id=body.voice_id,
            file_name=file_name,
            name=body.name or body.voice_id,
            description=body.description,
            category=body.category,
            language=body.language,
            gender=body.gender,
            labels=body.labels,
            owner=body.owner,
            version=body.version,
            enabled=body.enabled,
        )
        voice = voice_service.get_voice_by_id(
            model.voice_session_factory, model.prompt_dir, body.voice_id
        )
        if voice is None:
            raise HTTPException(status_code=500, detail="创建后读取音色失败")
        return with_audio_url(request, voice)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating speaker {body.voice_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/speakers/{voice_id}", response_model=VoiceInfo)
async def patch_speaker(voice_id: str, body: VoiceUpdateRequest, request: Request):
    try:
        ok = voice_service.update_voice(
            model.voice_session_factory, model.prompt_dir, voice_id, body
        )
        if not ok:
            raise HTTPException(status_code=404, detail=f"speaker '{voice_id}' 不存在")
        voice = voice_service.get_voice_by_id(
            model.voice_session_factory, model.prompt_dir, voice_id
        )
        if voice is None:
            raise HTTPException(status_code=404, detail=f"speaker '{voice_id}' 不存在")
        return with_audio_url(request, voice)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error patching speaker {voice_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
