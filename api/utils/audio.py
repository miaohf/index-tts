from __future__ import annotations

import io
import mimetypes
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import numpy as np
import soundfile as sf
from fastapi import Request
from fastapi.responses import FileResponse

from api.config import public_base_url
from api.schemas import VoiceInfo


def merge_wav_bytes(wav_bytes_list: list[bytes], interval_silence_ms: int = 0) -> bytes:
    """将多段 WAV bytes 按顺序拼接，可在段间插入静音。"""
    if not wav_bytes_list:
        raise ValueError("wav_bytes_list is empty")
    if len(wav_bytes_list) == 1:
        return wav_bytes_list[0]

    arrays: list[np.ndarray] = []
    sample_rate: int | None = None

    for wav_bytes in wav_bytes_list:
        data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        if sample_rate is None:
            sample_rate = sr
        arrays.append(data)

    parts: list[np.ndarray] = []
    silence = (
        np.zeros(int(sample_rate * interval_silence_ms / 1000), dtype=np.float32)
        if interval_silence_ms > 0
        else None
    )
    for i, arr in enumerate(arrays):
        parts.append(arr)
        if silence is not None and i < len(arrays) - 1:
            parts.append(silence)

    merged = np.concatenate(parts)
    out = io.BytesIO()
    sf.write(out, merged, sample_rate, format="WAV", subtype="PCM_16")
    return out.getvalue()


def encode_audio_bytes(wav_data: np.ndarray, sample_rate: int, response_format: str = "wav") -> tuple[bytes, str]:
    fmt = response_format.lower()
    buffer = io.BytesIO()
    sf.write(buffer, wav_data, sample_rate, format="WAV", subtype="PCM_16")
    wav_bytes = buffer.getvalue()
    return transcode_wav_bytes(wav_bytes, response_format=fmt)


def transcode_wav_bytes(wav_bytes: bytes, response_format: str = "wav") -> tuple[bytes, str]:
    fmt = response_format.lower()
    if fmt == "wav":
        return wav_bytes, "audio/wav"
    if fmt == "mp3":
        return _wav_to_mp3_bytes(wav_bytes), "audio/mpeg"
    if fmt == "opus":
        return _wav_to_opus_bytes(wav_bytes), "audio/opus"
    raise ValueError(f"Unsupported response_format: {response_format}")


def _wav_to_ffmpeg_output(wav_bytes: bytes, output_args: list[str], *, format_name: str) -> bytes:
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", *output_args, "pipe:1"],
            input=wav_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"response_format={format_name} requires ffmpeg installed on server") from exc
    except subprocess.CalledProcessError as exc:
        stderr_text = exc.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"ffmpeg failed to convert wav to {format_name}: {stderr_text}") from exc
    return result.stdout


def _wav_to_mp3_bytes(wav_bytes: bytes) -> bytes:
    return _wav_to_ffmpeg_output(wav_bytes, ["-f", "mp3"], format_name="mp3")


def _wav_to_opus_bytes(wav_bytes: bytes) -> bytes:
    """WAV → Ogg Opus（对齐 OpenAI response_format=opus）。"""
    return _wav_to_ffmpeg_output(
        wav_bytes,
        ["-c:a", "libopus", "-f", "ogg"],
        format_name="opus",
    )


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
