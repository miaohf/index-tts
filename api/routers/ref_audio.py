import logging
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from api.schemas import UploadRefAudioResponse
from api.services.ephemeral_audio import upload_ephemeral_ref

logger = logging.getLogger("indextts2-api")
router = APIRouter(tags=["ref-audio"], prefix="/ref-audio")


@router.post("/upload", response_model=UploadRefAudioResponse)
async def upload_ref_audio(
    source_file: UploadFile = File(...),
    session_id: str = Form(..., description="会话 ID，通常为 video_id"),
    segment_id: Optional[str] = Form(
        default=None,
        description="分片文件名；省略时使用上传文件的原始文件名（如 8efb100a_0000_SPEAKER_00_vocals.mp3）",
    ),
):
    """
    上传临时参考音（视频翻译分片），不入 SQLite。

    文件保存在 `assets/ephemeral/{session_id}/`；返回的 `ref_path` 用于
    `POST /v1/audio/speech` 的 `prompt_speech_path`。
    """
    return await upload_ephemeral_ref(
        session_id=session_id,
        source_file=source_file,
        segment_id=segment_id,
    )
