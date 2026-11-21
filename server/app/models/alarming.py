"""Alarming (Phase 4): alarm rules (AAO), alarms and their targets, police notices,
external interfaces (plugins) and their event log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin, utcnow
from app.models.operations import Keyword

RULE_ITEM_KINDS = ("vehicle_type", "vehicle", "station", "ric", "alarm_group", "interface")


class AlarmRule(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Alarm- und Ausrückeordnung (AAO) of one keyword in one control centre (optionally per area)."""

    __tablename__ = "alarm_rules"
    __table_args__ = (
        Index(
            "uq_alarm_rules_cc_keyword_area",
            "control_center_id",
            "keyword_id",
            text("coalesce(area_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id", ondelete="RESTRICT"))
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("control_center_areas.id", ondelete="RESTRICT")
    )
    name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    keyword: Mapped[Keyword] = relationship(lazy="selectin")
    items: Mapped[list[AlarmRuleItem]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="(AlarmRuleItem.stage, AlarmRuleItem.position)",
    )


class AlarmRuleItem(Base):
    """One line of an AAO: what to alarm in which stage (Alarmierungsschleife)."""

    __tablename__ = "alarm_rule_items"
    __table_args__ = (
        CheckConstraint("stage BETWEEN 1 AND 9", name="stage_range"),
        CheckConstraint("count BETWEEN 1 AND 20", name="count_range"),
        CheckConstraint(
            "(kind = 'vehicle_type' AND vehicle_type_id IS NOT NULL)"
            " OR (kind = 'vehicle' AND vehicle_id IS NOT NULL)"
            " OR (kind = 'station' AND station_id IS NOT NULL) OR (kind = 'ric' AND ric_id IS NOT NULL)"
            " OR (kind = 'alarm_group' AND alarm_group_id IS NOT NULL)"
            " OR (kind = 'interface' AND interface_id IS NOT NULL)",
            name="target_matches_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alarm_rules.id", ondelete="CASCADE"), index=True)
    stage: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16))
    count: Mapped[int] = mapped_column(Integer, default=1)
    vehicle_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicle_types.id", ondelete="RESTRICT")
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="RESTRICT"))
    station_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stations.id", ondelete="RESTRICT"))
    ric_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rics.id", ondelete="RESTRICT"))
    alarm_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alarm_groups.id", ondelete="RESTRICT")
    )
    interface_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("interfaces.id", ondelete="RESTRICT"))
    note: Mapped[str | None] = mapped_column(String(300))


class Alarm(UUIDPrimaryKeyMixin, Base):
    """A confirmed alarm (Alarmierung) – immutable record with its delivery results."""

    __tablename__ = "alarms"
    __table_args__ = (Index("uq_alarms_incident_idempotency", "incident_id", "idempotency_key", unique=True),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="RESTRICT"), index=True
    )
    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))  # detects reuse of a key with other content
    kind: Mapped[str] = mapped_column(String(16))  # initial | follow_up | manual
    stage: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16))  # simulation | real (operation mode at that time)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | completed | partial
    note: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    triggered_by_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    targets: Mapped[list[AlarmTarget]] = relationship(
        lazy="selectin", order_by="AlarmTarget.id", cascade="all, delete-orphan"
    )


class AlarmTarget(Base):
    __tablename__ = "alarm_targets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alarm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alarms.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(16))  # vehicle | station | ric | interface
    target_id: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(String(300))
    # simulated | sent | failed | skipped | not_delivered | pending
    delivery_status: Mapped[str] = mapped_column(String(16), default="pending")
    detail: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column()


class PoliceNotice(UUIDPrimaryKeyMixin, Base):
    """Information notice "Polizei informieren" – never transmitted anywhere by the system."""

    __tablename__ = "police_notices"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="RESTRICT"), index=True
    )
    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    keyword_code: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column()
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_by_name: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(String(1000))


class Interface(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Configured external interface (plugin instance). New interfaces are always disabled."""

    __tablename__ = "interfaces"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'global' AND control_center_id IS NULL AND station_id IS NULL)"
            " OR (scope = 'control_center' AND control_center_id IS NOT NULL AND station_id IS NULL)"
            " OR (scope = 'station' AND control_center_id IS NOT NULL AND station_id IS NOT NULL)",
            name="scope_consistent",
        ),
    )

    plugin_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    scope: Mapped[str] = mapped_column(String(16))  # global | control_center | station
    control_center_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secret_encrypted: Mapped[str | None] = mapped_column(Text)
    secret_hint: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # unknown | ok | error
    last_ok_at: Mapped[datetime | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column()


class InterfaceEvent(Base):
    __tablename__ = "interface_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    interface_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interfaces.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8))  # info | warning | error
    kind: Mapped[str] = mapped_column(String(16))  # test | delivery | redirected | config | status
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
