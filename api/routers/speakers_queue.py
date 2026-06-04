import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from api.schemas import SpeakersListResponse, UploadAudioResponse, VoiceCreateRequest, VoiceInfo, VoiceUpdateRequest
from api.services.speaker_read import download_speaker_audio, list_speakers
from api.services.speaker_write import (
    create_speaker,
    delete_speaker,
    update_speaker,
    upload_speaker_audio,
)

logger = logging.getLogger("indextts2-api")
router = APIRouter(tags=["speakers"])


@router.get("/speakers/{voice_id}/audio", name="download_speaker_audio")
async def queue_download_speaker_audio(voice_id: str):
    return download_speaker_audio(voice_id)


@router.get("/speakers", response_model=SpeakersListResponse)
async def queue_get_speakers(
    request: Request,
    language: Optional[str] = Query(default=None),
    gender: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    sort_by: str = Query(default="voice_id"),
    sort_order: str = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """返回音色列表（SQLAlchemy），支持筛选、排序和分页。"""
    return list_speakers(
        request,
        language=language,
        gender=gender,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.post("/speakers", response_model=VoiceInfo, status_code=201)
async def queue_create_speaker(body: VoiceCreateRequest, request: Request):
    """创建音色元数据（可后续通过 /upload_audio 上传参考音频）。"""
    return create_speaker(body, request)


@router.put("/speakers", response_model=VoiceInfo)
async def queue_upsert_speaker(body: VoiceCreateRequest, request: Request):
    """创建或更新音色元数据（与 POST /speakers 相同，返回 200）。"""
    return create_speaker(body, request)


@router.patch("/speakers/{voice_id}", response_model=VoiceInfo)
async def queue_patch_speaker(voice_id: str, body: VoiceUpdateRequest, request: Request):
    return update_speaker(voice_id, body, request)


@router.put("/speakers/{voice_id}", response_model=VoiceInfo)
async def queue_put_speaker(voice_id: str, body: VoiceUpdateRequest, request: Request):
    return update_speaker(voice_id, body, request)


@router.delete("/speakers/{voice_id}")
async def queue_delete_speaker(
    voice_id: str,
    remove_file: bool = Query(default=False, description="是否同时删除磁盘上的参考音频文件"),
):
    return delete_speaker(voice_id, remove_file=remove_file)


@router.delete("/speakers")
async def queue_delete_speaker_by_query(
    voice_id: str = Query(..., description="要删除的 voice_id"),
    remove_file: bool = Query(default=False, description="是否同时删除磁盘上的参考音频文件"),
):
    return delete_speaker(voice_id, remove_file=remove_file)


@router.post("/upload_audio", response_model=UploadAudioResponse)
async def queue_upload_audio(
    source_file: UploadFile = File(...),
    voice_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    language: str = Form(...),
    gender: str = Form(...),
):
    return await upload_speaker_audio(
        source_file=source_file,
        voice_id=voice_id,
        name=name,
        description=description,
        language=language,
        gender=gender,
    )
