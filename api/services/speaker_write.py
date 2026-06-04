from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request, UploadFile

from api.config import max_upload_bytes
from api.schemas import UploadAudioResponse, VoiceCreateRequest, VoiceInfo, VoiceUpdateRequest
from api.services import voices as voice_service
from api.utils.audio import with_audio_url
from api.voice_context import get_voice_context

logger = logging.getLogger("indextts2-api")


def validate_voice_id(voice_id: str) -> str:
    v = voice_id.strip()
    if not v:
        raise HTTPException(status_code=400, detail="voice_id 不能为空")
    if any(c in v for c in ("/", "\\", "\x00")) or ".." in v:
        raise HTTPException(status_code=400, detail="voice_id 不能包含路径分隔符或非法片段")
    return v


def _remove_stale_speaker_files(prompt_dir: str, voice_id: str, keep_name: str) -> None:
    """删除同一 voice_id 下扩展名已变更的旧参考音频。"""
    for ext in (".wav", ".mp3"):
        candidate = f"{voice_id}{ext}"
        if candidate == keep_name:
            continue
        path = os.path.join(prompt_dir, candidate)
        if os.path.isfile(path):
            try:
                os.remove(path)
                logger.info("Removed stale speaker audio: %s", path)
            except OSError as e:
                logger.warning("Failed to remove stale speaker audio %s: %s", path, e)


def create_speaker(body: VoiceCreateRequest, request: Request) -> VoiceInfo:
    file_name = body.file_name or f"{body.voice_id}.wav"
    voice_session_factory, prompt_dir = get_voice_context()
    try:
        voice_service.upsert_voice(
            voice_session_factory,
            prompt_dir,
            voice_id=body.voice_id,
            file_name=file_name,
            name=body.name or body.voice_id,
            description=body.description,
            language=body.language,
            gender=body.gender,
        )
        voice = voice_service.get_voice_by_id(voice_session_factory, prompt_dir, body.voice_id)
        if voice is None:
            raise HTTPException(status_code=500, detail="创建后读取音色失败")
        return with_audio_url(request, voice)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating speaker %s: %s", body.voice_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


def update_speaker(voice_id: str, body: VoiceUpdateRequest, request: Request) -> VoiceInfo:
    voice_session_factory, prompt_dir = get_voice_context()
    try:
        ok = voice_service.update_voice(voice_session_factory, prompt_dir, voice_id, body)
        if not ok:
            raise HTTPException(status_code=404, detail=f"speaker '{voice_id}' 不存在")
        voice = voice_service.get_voice_by_id(voice_session_factory, prompt_dir, voice_id)
        if voice is None:
            raise HTTPException(status_code=404, detail=f"speaker '{voice_id}' 不存在")
        return with_audio_url(request, voice)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating speaker %s: %s", voice_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


def delete_speaker(voice_id: str, *, remove_file: bool = False) -> dict:
    vid = validate_voice_id(voice_id)
    voice_session_factory, prompt_dir = get_voice_context()
    try:
        ok = voice_service.delete_voice(
            voice_session_factory,
            prompt_dir,
            vid,
            remove_file=remove_file,
        )
        if not ok:
            raise HTTPException(status_code=404, detail=f"speaker '{vid}' 不存在")
        return {"status": "success", "voice_id": vid, "message": "音色已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting speaker %s: %s", vid, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


async def upload_speaker_audio(
    *,
    source_file: UploadFile,
    voice_id: str,
    name: str,
    description: str,
    language: str,
    gender: str,
) -> UploadAudioResponse:
    save_path: Optional[str] = None
    file_existed_before = False
    voice_session_factory, prompt_dir = get_voice_context()
    try:
        if not source_file.filename:
            raise HTTPException(
                status_code=400,
                detail=(
                    "未上传音频文件。请使用 multipart/form-data 且包含 source_file 字段；"
                    "若仅需录入元数据（无文件），请使用 POST /speakers（application/json）。"
                ),
            )
        ext = Path(source_file.filename).suffix.lower()
        if ext not in (".wav", ".mp3"):
            raise HTTPException(status_code=400, detail="只支持 WAV 和 MP3 格式的音频文件")

        vid = validate_voice_id(voice_id)
        save_name = f"{vid}{ext}"

        os.makedirs(prompt_dir, exist_ok=True)
        save_path = os.path.join(prompt_dir, save_name)
        file_existed_before = os.path.exists(save_path)

        content = await source_file.read()
        limit = max_upload_bytes()
        if len(content) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，最大允许 {limit // (1024 * 1024)} MB",
            )

        with open(save_path, "wb") as f:
            f.write(content)

        _remove_stale_speaker_files(prompt_dir, vid, save_name)

        voice_service.upsert_voice(
            voice_session_factory,
            prompt_dir,
            voice_id=vid,
            file_name=save_name,
            name=name.strip() or vid,
            description=description,
            language=language,
            gender=gender,
        )
        voice = voice_service.get_voice_by_id(voice_session_factory, prompt_dir, vid)
        if voice is None:
            raise HTTPException(status_code=500, detail="上传后读取音色失败")
        logger.info("Speaker audio saved and upserted: %s", save_path)

        return UploadAudioResponse(
            status="success",
            message="音频文件上传成功",
            file_path=save_path,
            speaker_name=voice.name,
            voice_id=vid,
        )
    except HTTPException:
        raise
    except Exception as e:
        if save_path and (not file_existed_before) and os.path.exists(save_path):
            try:
                os.remove(save_path)
            except OSError:
                logger.warning("Failed to clean up audio file after DB error: %s", save_path)
        logger.error("Failed to upload speaker audio: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传音频文件失败: {str(e)}") from e
