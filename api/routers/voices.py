import logging
from typing import Optional

from fastapi import APIRouter, File, Form, Query, Request, UploadFile

from api.schemas import OpenAIVoice, OpenAIVoiceListResponse, VoiceCreateRequest, VoiceUpdateRequest
from api.services.openai_voice import (
    create_openai_voice,
    create_openai_voice_metadata,
    get_openai_voice,
    list_openai_voices,
    update_openai_voice,
)
from api.services.voice_read import download_voice_audio
from api.services.voice_write import delete_voice

logger = logging.getLogger("indextts2-api")
router = APIRouter(tags=["audio"])


@router.get("/v1/audio/voices", response_model=OpenAIVoiceListResponse)
async def list_voices_endpoint(
    request: Request,
    language: Optional[str] = Query(default=None),
    gender: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    sort_by: str = Query(default="voice_id"),
    sort_order: str = Query(default="asc"),
    limit: int = Query(default=20, ge=1, le=200),
    after: Optional[str] = Query(default=None, description="分页游标，传上一页 last_id"),
):
    """列出音色（OpenAI `audio.voice` 列表格式）。"""
    return list_openai_voices(
        request,
        language=language,
        gender=gender,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        after=after,
    )


@router.get("/v1/audio/voices/{voice_id}", response_model=OpenAIVoice)
async def get_voice_endpoint(voice_id: str, request: Request):
    return get_openai_voice(request, voice_id)


@router.get("/v1/audio/voices/{voice_id}/audio", name="download_voice_audio")
async def download_voice_audio_endpoint(voice_id: str):
    return download_voice_audio(voice_id)


@router.post("/v1/audio/voices", response_model=OpenAIVoice, status_code=200)
async def create_voice_endpoint(
    request: Request,
    name: str = Form(...),
    audio_sample: UploadFile = File(...),
    language: str = Form(...),
    gender: str = Form(...),
    description: str = Form(default=""),
    voice_id: Optional[str] = Form(default=None),
):
    """创建音色并上传参考音频（对齐 OpenAI POST /v1/audio/voices multipart）。"""
    return await create_openai_voice(
        request,
        name=name,
        audio_sample=audio_sample,
        voice_id=voice_id,
        description=description,
        language=language,
        gender=gender,
    )


@router.post(
    "/v1/audio/voices/metadata",
    response_model=OpenAIVoice,
    status_code=201,
    include_in_schema=True,
)
async def create_voice_metadata_endpoint(body: VoiceCreateRequest, request: Request):
    """仅创建元数据（无音频文件）；扩展端点，非 OpenAI 标准。"""
    return create_openai_voice_metadata(request, body)


@router.patch("/v1/audio/voices/{voice_id}", response_model=OpenAIVoice)
async def patch_voice_endpoint(voice_id: str, body: VoiceUpdateRequest, request: Request):
    return update_openai_voice(request, voice_id, body)


@router.put("/v1/audio/voices/{voice_id}", response_model=OpenAIVoice)
async def put_voice_endpoint(voice_id: str, body: VoiceUpdateRequest, request: Request):
    return update_openai_voice(request, voice_id, body)


@router.delete("/v1/audio/voices/{voice_id}")
async def delete_voice_endpoint(
    voice_id: str,
    remove_file: bool = Query(default=False, description="是否同时删除磁盘上的参考音频文件"),
):
    return delete_voice(voice_id, remove_file=remove_file)
