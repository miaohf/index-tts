import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.inference import model
from api.services import voices as voice_service

logger = logging.getLogger("indextts2-api")

router = APIRouter(tags=["upload"])


def _validate_voice_id(voice_id: str) -> str:
    v = voice_id.strip()
    if not v:
        raise HTTPException(status_code=400, detail="voice_id 不能为空")
    if any(c in v for c in ("/", "\\", "\x00")) or ".." in v:
        raise HTTPException(status_code=400, detail="voice_id 不能包含路径分隔符或非法片段")
    return v


@router.post("/upload_audio")
async def upload_audio(
    source_file: UploadFile = File(...),
    voice_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    language: str = Form(...),
    gender: str = Form(...),
    category: Optional[str] = Form(default=None),
    owner: Optional[str] = Form(default=None),
    version: Optional[str] = Form(default=None),
    enabled: bool = Form(default=True),
    labels_json: Optional[str] = Form(default=None),
):
    save_path: Optional[str] = None
    file_existed_before = False
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

        vid = _validate_voice_id(voice_id)
        save_name = f"{vid}{ext}"

        os.makedirs(model.prompt_dir, exist_ok=True)
        save_path = os.path.join(model.prompt_dir, save_name)
        file_existed_before = os.path.exists(save_path)

        labels: Optional[dict] = None
        if labels_json:
            try:
                raw = json.loads(labels_json)
                if not isinstance(raw, dict):
                    raise ValueError("labels_json 必须是 JSON 对象")
                labels = {str(k): str(v) for k, v in raw.items()}
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"labels_json 非法: {e}")

        content = await source_file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        voice_service.upsert_voice(
            model.voice_session_factory,
            model.prompt_dir,
            voice_id=vid,
            file_name=save_name,
            name=name.strip() or vid,
            description=description,
            category=category,
            language=language,
            gender=gender,
            labels=labels,
            owner=owner,
            version=version,
            enabled=enabled,
        )
        logger.info(f"成功保存音频文件并写入音色库: {save_path}")

        return {
            "status": "success",
            "message": "音频文件上传成功",
            "file_path": save_path,
            "speaker_name": vid,
            "voice_id": vid,
        }
    except HTTPException:
        raise
    except Exception as e:
        if save_path and (not file_existed_before) and os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception:
                logger.warning(f"写库失败后清理音频文件失败: {save_path}")
        logger.error(f"上传音频文件失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传音频文件失败: {str(e)}")
