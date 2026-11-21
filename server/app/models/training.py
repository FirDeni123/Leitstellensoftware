"""Training (Phase 7): scenarios, sessions with an AI (or rule-based) caller, transcript, evaluation.

Training calls never touch real telephony: they are emergency calls with ``source = training``
that exist only inside the system, and they are refused in real operation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin, utcnow
from app.models.operations import Keyword

DIFFICULTIES = ("easy", "medium", "hard")
SESSION_STATES = ("ringing", "active", "ended", "evaluated", "cancelled")
MESSAGE_ROLES = ("dispatcher", "caller", "instructor", "system")


class TrainingScenario(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "training_scenarios"
    __table_args__ = (CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="difficulty_valid"),)

    control_center_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )  # None = available to every control centre
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(16), default="medium")
    keyword_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("keywords.id", ondelete="RESTRICT"))
    persona: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    opening_line: Mapped[str] = mapped_column(Text)
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    keyword: Mapped[Keyword | None] = relationship(lazy="selectin")


class TrainingSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "training_sessions"

    scenario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("training_scenarios.id", ondelete="RESTRICT"))
    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    trainee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    trainee_name: Mapped[str] = mapped_column(String(200))
    instructor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    instructor_name: Mapped[str | None] = mapped_column(String(200))
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emergency_calls.id", ondelete="SET NULL"), unique=True
    )
    status: Mapped[str] = mapped_column(String(16), default="ringing")
    caller_mode: Mapped[str] = mapped_column(String(16))  # claude | rules
    model: Mapped[str | None] = mapped_column(String(64))
    scenario_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB
    )  # evaluation uses the scenario as started
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    answered_at: Mapped[datetime | None] = mapped_column()
    ended_at: Mapped[datetime | None] = mapped_column()
    # instructions not yet given to the caller: [{"text", "author", "immediate"}] (instructors only)
    pending_instructions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class TrainingMessage(Base):
    __tablename__ = "training_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(default=utcnow)
    role: Mapped[str] = mapped_column(String(16))  # dispatcher | caller | instructor | system
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        String(16)
    )  # text | voice | claude | rules | opening | instructor | system
    latency_ms: Mapped[int | None] = mapped_column(Integer)  # time to the first spoken sentence of a reply
    author_name: Mapped[str | None] = mapped_column(String(200))


class TrainingEvaluation(Base):
    __tablename__ = "training_evaluations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    method: Mapped[str] = mapped_column(String(16))  # claude | rules
    model: Mapped[str | None] = mapped_column(String(64))
    score: Mapped[int] = mapped_column(Integer)  # 0–100 (share of fulfilled required items)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    feedback: Mapped[dict[str, Any]] = mapped_column(JSONB)
