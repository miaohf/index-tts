from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from api.schemas import OpenAISpeechRequest, TextToSpeechRequest
from api.services.queue_progress_service import get_queue_progress, get_queue_status
from api.services.queue_query_service import (
    get_group_audio_content,
    get_group_detail,
    get_job_audio_content,
    get_job_detail,
    wait_for_request_audio_content,
)
from api.services.queue_submit_service import (
    AUTO_SPLIT_SEGMENT_LENGTH,
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    enqueue_and_wait,
    enqueue_group_and_wait,
    should_split,
    to_payload,
)
from api.text_segment import split_text
from api.utils.audio import transcode_wav_bytes

logger = logging.getLogger("indextts2-tts")
router = APIRouter(tags=["tts"])


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    return get_job_detail(job_id)


@router.get("/jobs/{job_id}/audio")
async def get_job_audio(job_id: str):
    return Response(content=get_job_audio_content(job_id), media_type="audio/wav")


@router.get("/jobs/group/{group_id}")
async def get_group(group_id: str):
    return get_group_detail(group_id)


@router.get("/jobs/group/{group_id}/audio")
async def get_group_audio(group_id: str):
    return Response(content=get_group_audio_content(group_id), media_type="audio/wav")


@router.get("/requests/{request_id}/audio")
async def get_request_audio(
    request_id: str,
    wait_timeout_seconds: int = Query(
        default=DEFAULT_WAIT_TIMEOUT_SECONDS,
        ge=1,
        le=1800,
        description="同步阻塞直至返回 WAV 或超时（504）；常规请直接用 POST /v1/audio/speech",
    ),
):
    audio = await wait_for_request_audio_content(request_id, wait_timeout_seconds)
    return Response(content=audio, media_type="audio/wav")


@router.get("/queue/status")
async def queue_status():
    return get_queue_status()


@router.get("/queue/progress")
async def queue_progress(
    include_groups: bool = Query(default=True, description="是否返回分段组进度明细"),
    max_group_items: int = Query(default=20, ge=1, le=200, description="最多返回多少个分段组条目"),
):
    return get_queue_progress(include_groups=include_groups, max_group_items=max_group_items)


@router.post("/v1/audio/speech")
async def queue_openai_audio_speech(
    body: OpenAISpeechRequest,
    wait_timeout_seconds: int = Query(default=DEFAULT_WAIT_TIMEOUT_SECONDS, ge=1, le=1800),
    auto_split: bool = Query(default=True, description="长文本自动分段并发到多 GPU（长度超过 INDEX_TTS_AUTO_SPLIT_THRESHOLD）"),
):
    """OpenAI Speech API 兼容：POST /v1/audio/speech（唯一对外 TTS 合成入口）。"""
    payload = to_payload(
        TextToSpeechRequest(
            text=body.input,
            voice=body.voice,
            prompt_speech_path=body.prompt_speech_path,
        )
    )

    if auto_split and should_split(body.input):
        segments = split_text(body.input, AUTO_SPLIT_SEGMENT_LENGTH)
        logger.info("/v1/audio/speech: text len=%d → %d segments (auto_split)", len(body.input), len(segments))
        result = await enqueue_group_and_wait(
            request_type="tts_v1",
            base_payload=payload,
            segments=segments,
            wait_timeout_seconds=wait_timeout_seconds,
            interval_silence_ms=200,
            client_request_id=None,
        )
    else:
        result = await enqueue_and_wait(
            request_type="tts_v1",
            payload=payload,
            wait_timeout_seconds=wait_timeout_seconds,
            client_request_id=None,
        )

    if body.response_format == "wav":
        return result

    try:
        audio_bytes, media_type = transcode_wav_bytes(result.body, response_format=body.response_format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return Response(content=audio_bytes, media_type=media_type)
