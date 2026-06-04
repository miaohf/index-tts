"""音色库上下文（不加载 TTS 推理模型）。"""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.orm import sessionmaker

from api.config import project_root
from api.database.engine import create_voice_session_factory


def resolve_prompt_dir() -> str:
    relative = os.environ.get("INDEX_TTS_PROMPT_DIR", "assets/speakers")
    if os.path.isabs(relative):
        base = relative
    else:
        base = os.path.join(project_root(), relative)
    base = os.path.abspath(base)
    if not os.path.exists(base):
        os.makedirs(base, exist_ok=True)
    return base


@lru_cache(maxsize=1)
def get_voice_context() -> tuple[sessionmaker, str]:
    prompt_dir = resolve_prompt_dir()
    return create_voice_session_factory(prompt_dir), prompt_dir
