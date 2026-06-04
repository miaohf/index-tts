"""参考音频路径解析：持久音色目录 + 临时 ephemeral 目录。"""

from __future__ import annotations

import os
from pathlib import Path

from api.config import EPHEMERAL_REF_PREFIX

_ALLOWED_AUDIO_EXTENSIONS = (".wav", ".mp3")


def validate_session_id(session_id: str) -> str:
    sid = session_id.strip()
    if not sid:
        raise ValueError("session_id 不能为空")
    if any(c in sid for c in ("/", "\\", "\x00")) or ".." in sid:
        raise ValueError("session_id 不能包含路径分隔符或非法片段")
    return sid


def sanitize_basename(name: str) -> str:
    """仅保留文件名部分，禁止路径穿越。"""
    base = os.path.basename(name.strip())
    if not base or base in (".", ".."):
        raise ValueError("文件名无效")
    if any(c in base for c in ("/", "\\", "\x00")) or ".." in base:
        raise ValueError("文件名不能包含路径分隔符或非法片段")
    return base


def validate_audio_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError("只支持 WAV 和 MP3 格式的音频文件")
    return ext


def build_ephemeral_ref_path(session_id: str, filename: str) -> str:
    return f"{EPHEMERAL_REF_PREFIX}{session_id}/{filename}"


def is_ephemeral_ref(ref: str) -> bool:
    normalized = ref.replace("\\", "/").lstrip("/")
    return normalized.startswith(EPHEMERAL_REF_PREFIX)


def _resolve_under_root(root: str, relative_parts: str) -> str | None:
    root_path = Path(root).resolve()
    candidate = (root_path / relative_parts).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError:
        return None
    return str(candidate)


def resolve_ref_audio_path(
    ref: str,
    *,
    prompt_dir: str,
    ephemeral_dir: str,
) -> str:
    """
    将 TTS/上传返回的 ref 解析为绝对路径。

    支持：
    - ``ephemeral/{session_id}/file.mp3`` → ephemeral 目录
    - ``file.wav`` / ``speakers/file.wav`` → 持久音色目录（兼容旧行为）
    """
    if not ref or not ref.strip():
        raise ValueError("prompt_speech_path 不能为空")

    normalized = ref.strip().replace("\\", "/").lstrip("/")

    if normalized.startswith(EPHEMERAL_REF_PREFIX):
        relative = normalized[len(EPHEMERAL_REF_PREFIX) :]
        if not relative or ".." in relative:
            raise ValueError(f"非法临时参考音路径: {ref}")
        resolved = _resolve_under_root(ephemeral_dir, relative)
        if resolved is None:
            raise ValueError(f"非法临时参考音路径: {ref}")
        return resolved

    if normalized.startswith("speakers/"):
        relative = normalized[len("speakers/") :]
    else:
        relative = os.path.basename(normalized)

    if not relative or ".." in relative:
        raise ValueError(f"非法参考音路径: {ref}")

    resolved = _resolve_under_root(prompt_dir, relative)
    if resolved is None:
        raise ValueError(f"非法参考音路径: {ref}")
    return resolved
