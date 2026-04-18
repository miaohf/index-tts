"""voices 表增加自增主键 id，voice_id 改为唯一业务键

Revision ID: 7f3a9b2c1d4e
Revises: 38d069d34930
Create Date: 2026-04-19

SQLite：备份子表 → 删表重建 voices → 回填 → 重建子表并恢复数据。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7f3a9b2c1d4e"
down_revision: Union[str, Sequence[str], None] = "38d069d34930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        raise NotImplementedError("本迁移仅实现 SQLite；其他数据库请自行调整。")
    rows = conn.execute(sa.text("PRAGMA table_info(voices)")).fetchall()
    col_names = [r[1] for r in rows]
    if "id" in col_names:
        return

    op.execute(sa.text("CREATE TABLE voices_backup AS SELECT * FROM voices"))
    op.execute(sa.text("CREATE TABLE voice_labels_backup AS SELECT * FROM voice_labels"))
    op.execute(sa.text("CREATE TABLE voice_stats_backup AS SELECT * FROM voice_stats"))

    op.drop_table("voice_labels")
    op.drop_table("voice_stats")
    op.drop_table("voices")

    op.create_table(
        "voices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("voice_id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("gender", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voice_id"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO voices (
                voice_id, name, description, category, language, gender,
                file_name, enabled, owner, version, created_at, updated_at
            )
            SELECT
                voice_id, name, description, category, language, gender,
                file_name, enabled, owner, version, created_at, updated_at
            FROM voices_backup
            """
        )
    )

    op.create_table(
        "voice_labels",
        sa.Column("voice_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["voice_id"], ["voices.voice_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("voice_id", "key"),
    )
    op.execute(sa.text("INSERT INTO voice_labels SELECT * FROM voice_labels_backup"))

    op.create_table(
        "voice_stats",
        sa.Column("voice_id", sa.String(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("total_audio_seconds", sa.Float(), nullable=False),
        sa.Column("last_used_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["voice_id"], ["voices.voice_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("voice_id"),
    )
    op.execute(sa.text("INSERT INTO voice_stats SELECT * FROM voice_stats_backup"))

    op.drop_table("voices_backup")
    op.drop_table("voice_labels_backup")
    op.drop_table("voice_stats_backup")


def downgrade() -> None:
    raise NotImplementedError("请从备份恢复；本迁移未实现无损 downgrade")
