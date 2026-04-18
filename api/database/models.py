from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Voice(Base):
    __tablename__ = "voices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voice_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    labels: Mapped[List["VoiceLabel"]] = relationship(
        "VoiceLabel",
        back_populates="voice",
        cascade="all, delete-orphan",
    )
    stats: Mapped[Optional["VoiceStat"]] = relationship(
        "VoiceStat",
        back_populates="voice",
        uselist=False,
        cascade="all, delete-orphan",
    )


class VoiceLabel(Base):
    __tablename__ = "voice_labels"

    voice_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("voices.voice_id", ondelete="CASCADE"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    voice: Mapped["Voice"] = relationship("Voice", back_populates="labels")


class VoiceStat(Base):
    __tablename__ = "voice_stats"

    voice_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("voices.voice_id", ondelete="CASCADE"),
        primary_key=True,
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_audio_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_used_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    voice: Mapped["Voice"] = relationship("Voice", back_populates="stats")
