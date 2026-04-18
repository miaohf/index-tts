from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import FileResponse

from api.config import public_base_url
from api.schemas import VoiceInfo


def speaker_audio_path(voice_id: str) -> str:
    """相对路径，与路由 GET /speakers/{voice_id}/audio 一致；前端可用「站点公网 origin + audio_path」拼接。"""
    return f"/speakers/{quote(voice_id, safe='')}/audio"


def resolve_speaker_audio_file(prompt_dir: str, voice: VoiceInfo) -> Optional[Path]:
    root = Path(prompt_dir).resolve()
    candidate = (root / voice.file_name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def voice_audio_url(request: Request, voice_id: str) -> str:
    base = public_base_url()
    if base:
        return f"{base.rstrip('/')}{speaker_audio_path(voice_id)}"
    return str(request.url_for("download_speaker_audio", voice_id=voice_id))


def with_audio_url(request: Request, voice: VoiceInfo) -> VoiceInfo:
    return voice.model_copy(
        update={
            "audio_url": voice_audio_url(request, voice.voice_id),
            "audio_path": speaker_audio_path(voice.voice_id),
        }
    )


def file_response_for_speaker(path: Path) -> FileResponse:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline",
    )
