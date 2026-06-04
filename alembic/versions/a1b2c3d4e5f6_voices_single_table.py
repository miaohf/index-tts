"""voices 单表：合并 stats，删除 labels 与冗余列

Revision ID: a1b2c3d4e5f6
Revises: 7f3a9b2c1d4e
Create Date: 2026-06-04

运行时亦可通过 api.database.engine.apply_voice_db_migrations 自动完成同等迁移。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "7f3a9b2c1d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        raise NotImplementedError("本迁移仅实现 SQLite")
    from api.database.engine import apply_voice_db_migrations

    apply_voice_db_migrations(conn.engine)


def downgrade() -> None:
    raise NotImplementedError("voices 单表迁移不可自动回滚")
