"""API 常量。"""

import os

VOICE_DB_FILENAME = "voices.db"


def project_root() -> str:
    """项目根目录（含 `api/`、`assets/` 的目录）。"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def resolve_voice_db_path(prompt_dir: str | None = None) -> str:
    """
    音色库 SQLite 文件绝对路径。
    `prompt_dir` 为 None 时使用环境变量 INDEX_TTS_PROMPT_DIR（默认 `assets/speakers`），
    相对路径相对于 project_root。
    """
    if prompt_dir is None:
        relative = os.environ.get("INDEX_TTS_PROMPT_DIR", "assets/speakers")
        base = os.path.join(project_root(), relative)
    else:
        base = (
            prompt_dir
            if os.path.isabs(prompt_dir)
            else os.path.join(project_root(), prompt_dir)
        )
    base = os.path.abspath(base)
    return os.path.join(base, VOICE_DB_FILENAME)


def voice_sqlalchemy_url() -> str:
    """Alembic / 工具使用的 DSN；可被环境变量覆盖。"""
    override = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get(
        "INDEX_TTS_VOICE_DATABASE_URL"
    )
    if override and override.strip():
        return override.strip()
    return f"sqlite:///{resolve_voice_db_path(None)}"


def public_base_url() -> str | None:
    """
    若设置环境变量 INDEX_TTS_PUBLIC_BASE_URL（例如 https://tts.example.com），
    则 speakers 列表/详情中的 audio_url 使用该前缀，避免固定为 127.0.0.1 等无法外发的地址。
    不要尾随斜杠，可带路径前缀（如 https://api.example.com/v1）。
    """
    v = os.environ.get("INDEX_TTS_PUBLIC_BASE_URL", "").strip()
    return v or None

VOICE_SORT_FIELDS = {
    "voice_id": "voice_id",
    "name": "name",
    "language": "language",
    "gender": "gender",
    "created_at": "created_at",
    "updated_at": "updated_at",
    "usage_count": "usage_count",
}
