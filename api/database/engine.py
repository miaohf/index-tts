from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from api.config import resolve_voice_db_path
from api.database.models import Base, Voice


def _pragma_column_names(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}


def _is_legacy_voice_schema(conn) -> bool:
    r = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='voices'")
    ).fetchone()
    if r is None:
        return False
    cols = _pragma_column_names(conn, "voices")
    return "request_count" not in cols or "category" in cols


def _recreate_voices_schema(engine: Engine) -> None:
    """将旧版 voices + voice_stats + voice_labels 合并为单表 voices。"""
    with engine.begin() as conn:
        if not _is_legacy_voice_schema(conn):
            return

        rows: list[tuple] = []
        has_voices = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='voices'")
        ).fetchone()
        if has_voices:
            vcols = _pragma_column_names(conn, "voices")
            has_stats = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='voice_stats'"
                )
            ).fetchone()
            if has_stats:
                rows = conn.execute(
                    text(
                        """
                        SELECT
                            v.id, v.voice_id, v.name, v.description,
                            v.language, v.gender, v.file_name,
                            COALESCE(s.request_count, 0),
                            COALESCE(s.total_audio_seconds, 0.0),
                            s.last_used_at,
                            v.created_at, v.updated_at
                        FROM voices v
                        LEFT JOIN voice_stats s ON s.voice_id = v.voice_id
                        ORDER BY v.id
                        """
                    )
                ).fetchall()
            else:
                sel = [
                    "id",
                    "voice_id",
                    "name",
                    "COALESCE(description, '')",
                    "language",
                    "gender",
                    'COALESCE(file_name, voice_id || \'.wav\')',
                    "COALESCE(created_at, '')",
                    "COALESCE(updated_at, '')",
                    "0",
                    "0.0",
                    "NULL",
                ]
                if "request_count" in vcols:
                    sel[9] = "COALESCE(request_count, 0)"
                if "total_audio_seconds" in vcols:
                    sel[10] = "COALESCE(total_audio_seconds, 0.0)"
                if "last_used_at" in vcols:
                    sel[11] = "last_used_at"
                rows = conn.execute(
                    text(f"SELECT {', '.join(sel)} FROM voices ORDER BY id")
                ).fetchall()

        conn.execute(text("DROP TABLE IF EXISTS voice_labels"))
        conn.execute(text("DROP TABLE IF EXISTS voice_stats"))
        conn.execute(text("DROP TABLE IF EXISTS voices"))

    Base.metadata.create_all(engine)

    if not rows:
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO voices (
                    id, voice_id, name, description, language, gender, file_name,
                    request_count, total_audio_seconds, last_used_at,
                    created_at, updated_at
                ) VALUES (
                    :id, :voice_id, :name, :description, :language, :gender, :file_name,
                    :request_count, :total_audio_seconds, :last_used_at,
                    :created_at, :updated_at
                )
                """
            ),
            [
                {
                    "id": r[0],
                    "voice_id": r[1],
                    "name": r[2],
                    "description": r[3] or "",
                    "language": r[4],
                    "gender": r[5],
                    "file_name": r[6],
                    "request_count": int(r[7] or 0),
                    "total_audio_seconds": float(r[8] or 0.0),
                    "last_used_at": r[9],
                    "created_at": r[10] or "",
                    "updated_at": r[11] or "",
                }
                for r in rows
            ],
        )
        max_id = max(int(r[0]) for r in rows)
        has_seq = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
            )
        ).fetchone()
        if has_seq:
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES ('voices', :seq)"
                ),
                {"seq": max_id},
            )


def apply_voice_db_migrations(engine: Engine) -> None:
    """确保 voices 为当前单表结构（可从旧库自动迁移）。"""
    _recreate_voices_schema(engine)
    Base.metadata.create_all(engine)


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
