from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page[T](ApiModel):
    items: list[T]
    total: int


class VersionedUpdate(ApiModel):
    """Every update carries the version the client last saw (optimistic locking)."""

    expected_version: int = Field(ge=1, description="Version des Datensatzes beim Laden")
