"""Schemas: training scenarios, sessions, transcript, evaluation, AI settings (Phase 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Difficulty = Literal["easy", "medium", "hard"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Short = Field(default=None, max_length=200)
Long = Field(default=None, max_length=1000)


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Short
    age: int | None = Field(default=None, ge=1, le=120)
    role: str | None = Short  # e.g. "Passantin", "Ehemann der Patientin"
    emotional_state: str | None = Short
    speech_style: str | None = Short
    phone: str | None = Field(default=None, max_length=64)


class Facts(BaseModel):
    """The truth of the scenario – what the caller knows (fictional data only)."""

    model_config = ConfigDict(extra="forbid")

    address: str | None = Field(default=None, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    location_hint: str | None = Long
    situation: str | None = Long
    persons: str | None = Long
    injuries: str | None = Long
    hazards: str | None = Long
    details: list[str] = Field(default_factory=list, max_length=30)
    unknown: list[str] = Field(default_factory=list, max_length=30)


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    label: str = Field(min_length=1, max_length=200)
    required: bool = True
    hints: list[str] = Field(default_factory=list, max_length=20)  # for the rule-based judgement


class ScenarioCreate(BaseModel):
    control_center_id: uuid.UUID | None = None  # None = all control centres (administrators)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    difficulty: Difficulty = "medium"
    keyword_id: uuid.UUID | None = None
    persona: Persona = Field(default_factory=Persona)
    facts: Facts = Field(default_factory=Facts)
    opening_line: str = Field(min_length=1, max_length=500)
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=30)
    is_active: bool = True


class ScenarioUpdate(BaseModel):
    expected_version: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    difficulty: Difficulty | None = None
    keyword_id: uuid.UUID | None = None
    persona: Persona | None = None
    facts: Facts | None = None
    opening_line: str | None = Field(default=None, min_length=1, max_length=500)
    checklist: list[ChecklistItem] | None = Field(default=None, max_length=30)
    is_active: bool | None = None


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    control_center_id: uuid.UUID | None
    title: str
    description: str | None
    difficulty: Difficulty
    keyword_id: uuid.UUID | None
    keyword_code: str | None = None
    keyword_name: str | None = None
    persona: dict[str, Any]
    facts: dict[str, Any]
    opening_line: str
    checklist: list[dict[str, Any]]
    is_active: bool
    version: int
    updated_at: datetime


class SessionStart(BaseModel):
    scenario_id: uuid.UUID
    control_center_id: uuid.UUID
    trainee_id: uuid.UUID | None = None  # None = myself; others only for instructors


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    source: Literal["text", "voice"] = "text"


class InstructionIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    immediate: bool = False  # the caller reacts at once instead of with the next reply


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    role: str
    text: str
    source: str
    latency_ms: int | None
    author_name: str | None


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    method: str
    model: str | None
    score: int
    metrics: dict[str, Any]
    checklist: list[dict[str, Any]]
    feedback: dict[str, Any]


class SessionOut(BaseModel):
    id: uuid.UUID
    scenario_id: uuid.UUID
    control_center_id: uuid.UUID
    title: str
    difficulty: str
    trainee_id: uuid.UUID
    trainee_name: str
    instructor_id: uuid.UUID | None
    instructor_name: str | None
    call_id: uuid.UUID | None
    call_status: str | None = None
    status: str
    caller_mode: str
    model: str | None
    created_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    score: int | None = None


class SessionDetail(SessionOut):
    messages: list[MessageOut]
    pending_instructions: list[dict[str, Any]] | None = None  # instructors only
    scenario: dict[str, Any] | None = None  # instructors always, the trainee after the exercise
    evaluation: EvaluationOut | None = None


class AiSettingsOut(BaseModel):
    enabled: bool
    model: str
    caller_effort: Effort
    evaluation_effort: Effort
    has_key: bool
    key_hint: str | None
    server_key: bool  # ILS_ANTHROPIC_API_KEY configured on the server
    base_url: str
    speech_to_text: bool  # faster-whisper installed
    version: int | None


class AiSettingsUpdate(BaseModel):
    expected_version: int | None = None
    enabled: bool | None = None
    model: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.\-]{2,63}$")
    caller_effort: Effort | None = None
    evaluation_effort: Effort | None = None
    api_key: SecretStr | None = Field(default=None, min_length=20, max_length=300)
    clear_key: bool = False


class AiTestOut(BaseModel):
    ok: bool
    model: str | None
    latency_ms: int | None
    message: str


class SpeechOut(BaseModel):
    text: str
    message: MessageOut | None


class TraineeOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
