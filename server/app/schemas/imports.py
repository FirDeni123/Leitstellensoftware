from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel

ImportKind = Literal["vehicles", "stations"]


class TargetFieldOut(ApiModel):
    key: str
    label: str
    required: bool
    hint: str


class ImportRowResult(ApiModel):
    row: int
    action: Literal["create", "update", "unchanged", "error", "skip"]
    values: dict[str, str]
    errors: list[str]
    warnings: list[str]
    changes: list[str]


class ImportJobSummary(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    kind: ImportKind
    status: Literal["uploaded", "validated", "committed", "discarded"]
    file_name: str
    sheet_name: str | None
    row_count: int
    summary: dict[str, int] | None
    created_at: datetime
    committed_at: datetime | None
    version: int


class ImportJobOut(ImportJobSummary):
    headers: list[str]
    sample_rows: list[list[str]]
    sheets: list[str] = Field(default_factory=list)
    fields: list[TargetFieldOut]
    column_mapping: dict[str, int | None] | None
    options: dict[str, Any]
    validation: list[ImportRowResult] | None


class MappingRequest(ApiModel):
    mapping: dict[str, int | None]
    update_existing: bool = False
    expected_version: int = Field(ge=1)


class CommitRequest(ApiModel):
    expected_version: int = Field(ge=1)
    skip_invalid: bool = Field(default=False, description="Fehlerhafte Zeilen ausdrücklich überspringen")
