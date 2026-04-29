from __future__ import annotations

import os

from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from api.config import resolve_voice_db_path
from api.database.models import Base, Voice


def _pragma_column_names(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}


def _migrate_voices_surrogate_pk(engine: Engine) -> None:
    """
    旧版库中 `voices` 以 `voice_id` 为主键且无自增 `id` 列；当前 ORM 需要 `id`。
    在保留 `voice_id` 及子表（voice_labels / voice_stats）的前提下重建表。
    """
    with engine.begin() as conn:
        r = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='voices'")
        ).fetchone()
        if r is None:
            return
        old_cols = _pragma_column_names(conn, "voices")
        if "id" in old_cols:
            return

        conn.execute(text('DROP TABLE IF EXISTS "voices_new"'))
        meta = MetaData()
        voices_new = Voice.__table__.to_metadata(meta, name="voices_new")
        conn.execute(CreateTable(voices_new))

        new_data_cols = [c.name for c in Voice.__table__.c if c.name != "id"]
        select_parts: list[str] = []
        for cname in new_data_cols:
            if cname in old_cols:
                if cname == "file_name":
                    select_parts.append(
                        """COALESCE("file_name", "voice_id" || '.' || 'wav')"""
                    )
                elif cname == "name":
                    select_parts.append("""COALESCE("name", "voice_id", '')""")
                elif cname == "description":
                    select_parts.append("""COALESCE("description", '')""")
                elif cname in ("created_at", "updated_at"):
                    select_parts.append(f"""COALESCE("{cname}", '')""")
                elif cname == "enabled":
                    select_parts.append("""COALESCE("enabled", 1)""")
                else:
                    select_parts.append(f'"{cname}"')
            else:
                if cname == "description":
                    select_parts.append("''")
                elif cname == "name":
                    select_parts.append("""COALESCE("voice_id", '')""")
                elif cname == "file_name":
                    select_parts.append("""("voice_id" || '.' || 'wav')""")
                elif cname in ("language", "gender", "category", "owner", "version"):
                    select_parts.append("NULL")
                elif cname == "enabled":
                    select_parts.append("1")
                elif cname in ("created_at", "updated_at"):
                    select_parts.append("''")
                else:
                    select_parts.append("NULL")

        col_list = ", ".join(f'"{c}"' for c in new_data_cols)
        sel = ", ".join(select_parts)
        conn.execute(
            text(f'INSERT INTO "voices_new" ({col_list}) SELECT {sel} FROM "voices"')
        )

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            conn.execute(text('DROP TABLE "voices"'))
            conn.execute(text('ALTER TABLE "voices_new" RENAME TO "voices"'))
        finally:
            conn.execute(text("PRAGMA foreign_keys=ON"))


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
        has_labels = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='voice_labels'"
            )
        ).fetchone()
        if has_labels:
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


def apply_voice_db_migrations(engine: Engine) -> None:
    """创建缺失表，并将旧版 `voices` 等结构升级到当前 ORM（可离线调用，无需加载 TTS）。"""
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    if insp.has_table("voices"):
        _migrate_voices_surrogate_pk(engine)
        _migrate_voices_language_gender_columns(engine)


def create_voice_session_factory(prompt_dir: str) -> sessionmaker[Session]:
    """创建音色库 Session 工厂，并确保表结构与迁移。"""
    db_path = resolve_voice_db_path(prompt_dir)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        pool_pre_ping=True,
    )
    apply_voice_db_migrations(engine)
    return sessionmaker(engine, class_=Session, expire_on_commit=False)
