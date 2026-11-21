from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin


class ImportJob(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """One Excel/CSV import: uploaded → mapped/validated → committed or discarded.

    The parsed rows are kept until the job is committed or discarded so that the
    administrator can review the complete preview before anything is written.
    """

    __tablename__ = "import_jobs"

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # vehicles | stations
    status: Mapped[str] = mapped_column(
        String(16), default="uploaded"
    )  # uploaded|validated|committed|discarded
    file_name: Mapped[str] = mapped_column(String(255))
    sheet_name: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    headers: Mapped[list[str]] = mapped_column(JSONB)
    rows: Mapped[list[list[str]] | None] = mapped_column(JSONB)  # cleared after commit/discard
    row_count: Mapped[int] = mapped_column(Integer)
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    validation: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    committed_at: Mapped[datetime | None] = mapped_column()
