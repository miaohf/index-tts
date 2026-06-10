import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from api.config import max_upload_bytes
from api.services.transcription import ResponseFormat, transcribe_upload

logger = logging.getLogger("indextts2-stt")

router = APIRouter(tags=["transcriptions"])

_TEXT_FORMATS = frozenset({"text", "srt", "vtt"})


@router.post("/v1/audio/transcriptions")
async def create_transcription(
    file: UploadFile = File(..., description="待转写音频文件"),
    model: str = Form(default="whisper-1", description="OpenAI 兼容模型名（实际尺寸见 INDEX_TTS_WHISPER_MODEL）"),
    language: Optional[str] = Form(default=None, description="ISO-639-1 语言代码，如 zh、en"),
    prompt: Optional[str] = Form(default=None, description="可选上下文提示"),
    response_format: ResponseFormat = Form(default="json"),
    temperature: float = Form(default=0.0, ge=0.0, le=1.0),
):
    """OpenAI Audio Transcriptions 兼容：POST /v1/audio/transcriptions。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="音频文件为空")

    max_bytes = max_upload_bytes()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，上限 {max_bytes} 字节（INDEX_TTS_MAX_UPLOAD_BYTES）",
        )

    logger.info(
        "Received /v1/audio/transcriptions: filename=%s size=%d model=%s language=%s format=%s",
        file.filename,
        len(content),
        model,
        language,
        response_format,
    )

    try:
        result = await transcribe_upload(
            content,
            file.filename,
            model=model,
            language=language,
            prompt=prompt,
            response_format=response_format,
            temperature=temperature,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Transcription error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"转写失败: {e}")

    if response_format in _TEXT_FORMATS:
        media_type = "text/plain" if response_format == "text" else "text/vtt"
        if response_format == "srt":
            media_type = "application/x-subrip"
        return PlainTextResponse(content=str(result), media_type=media_type)

    return JSONResponse(content=result)
