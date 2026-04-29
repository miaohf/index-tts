#!/usr/bin/env python3
"""离线升级音色库 SQLite（如为 `voices` 增加自增 `id`），无需启动 TTS / uvicorn。

示例（项目根目录）::

    uv run python scripts/migrate_voices_db.py --db assets/speakers/voices.db
    uv run python scripts/migrate_voices_db.py --prompt-dir assets/speakers
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine

from api.config import resolve_voice_db_path
from api.database.engine import apply_voice_db_migrations


def main() -> None:
    p = argparse.ArgumentParser(description="升级音色库 SQLite 表结构")
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--db",
        metavar="PATH",
        help="voices.db 路径（相对当前工作目录或绝对路径）",
    )
    g.add_argument(
        "--prompt-dir",
        metavar="DIR",
        help="提示音目录，库为其下 voices.db；未设置时与 INDEX_TTS_PROMPT_DIR 默认一致",
    )
    args = p.parse_args()
    if args.db:
        db_path = os.path.abspath(args.db)
    else:
        db_path = resolve_voice_db_path(args.prompt_dir)
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        pool_pre_ping=True,
    )
    apply_voice_db_migrations(engine)
    print(f"迁移完成: {db_path}")


if __name__ == "__main__":
    main()
