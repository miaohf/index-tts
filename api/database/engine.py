from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from api.config import resolve_voice_db_path
from api.database.models import Base


def _migrate_voices_language_gender_columns(engine: Engine) -> None:
    """为旧库增加 language/gender 列，并从 voice_labels 迁移 language、gender、sex。"""
    with engine.begin() as conn:
        r = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='voices'")
        ).fetchone()
        if r is None:
            return
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(voices)"))}
        if "language" not in cols:
            conn.execute(text("ALTER TABLE voices ADD COLUMN language TEXT"))
        if "gender" not in cols:
            conn.execute(text("ALTER TABLE voices ADD COLUMN gender TEXT"))
        conn.execute(
            text(
                """
                UPDATE voices SET language = (
                    SELECT l.value FROM voice_labels l
                    WHERE l.voice_id = voices.voice_id AND l.key = 'language' LIMIT 1
                )
                WHERE (language IS NULL OR language = '')
                AND EXISTS (
                    SELECT 1 FROM voice_labels l
                    WHERE l.voice_id = voices.voice_id AND l.key = 'language'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE voices SET gender = (
                    SELECT l.value FROM voice_labels l
                    WHERE l.voice_id = voices.voice_id AND l.key IN ('gender', 'sex') LIMIT 1
                )
                WHERE (gender IS NULL OR gender = '')
                AND EXISTS (
                    SELECT 1 FROM voice_labels l
                    WHERE l.voice_id = voices.voice_id AND l.key IN ('gender', 'sex')
                )
                """
            )
        )


def create_voice_session_factory(prompt_dir: str) -> sessionmaker[Session]:
    """创建音色库 Session 工厂，并确保表结构与迁移。"""
    db_path = resolve_voice_db_path(prompt_dir)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        pool_pre_ping=True,
    )
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    if insp.has_table("voices"):
        _migrate_voices_language_gender_columns(engine)
    return sessionmaker(engine, class_=Session, expire_on_commit=False)
