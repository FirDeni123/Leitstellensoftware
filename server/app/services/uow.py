"""Unit of work: one database transaction + its audit entries + its realtime events.

Audit entries are written in the *same* transaction as the change itself (a change
without an audit entry cannot be committed). Realtime events are only published after a
successful commit, so clients never see changes that were rolled back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var
from app.core.permissions import P
from app.models import AuditLog, User
from app.realtime.bus import BusMessage, EventBus


@dataclass(slots=True)
class Actor:
    user_id: uuid.UUID | None
    name: str

    @classmethod
    def of(cls, user: User | None) -> Actor:
        if user is None:
            return cls(None, "System")
        return cls(user.id, f"{user.display_name} ({user.username})")


SYSTEM_ACTOR = Actor(None, "System")


class UnitOfWork:
    def __init__(self, session: AsyncSession, bus: EventBus, actor: Actor = SYSTEM_ACTOR) -> None:
        self.session = session
        self.bus = bus
        self.actor = actor
        self._pending: list[BusMessage] = []

    def emit(
        self,
        topic: str,
        data: dict[str, Any],
        *,
        channels: list[str] | None = None,
        required_permission: str | None = None,
    ) -> None:
        self._pending.append(
            BusMessage(
                kind="event",
                topic=topic,
                data=data,
                channels=channels or ["broadcast"],
                required_permission=required_permission,
            )
        )

    def control(self, topic: str, data: dict[str, Any]) -> None:
        self._pending.append(BusMessage(kind="control", topic=topic, data=data, channels=[]))

    def audit(
        self,
        action: str,
        entity_type: str,
        entity_id: Any,
        summary: str,
        *,
        changes: dict[str, Any] | None = None,
        control_center_id: uuid.UUID | None = None,
    ) -> None:
        entry = AuditLog(
            actor_user_id=self.actor.user_id,
            actor_name=self.actor.name,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            control_center_id=control_center_id,
            summary=summary,
            changes=changes,
            request_id=request_id_var.get(),
        )
        self.session.add(entry)
        self.emit(
            "audit.created",
            {
                "action": action,
                "entity_type": entity_type,
                "entity_id": entry.entity_id,
                "summary": summary,
                "actor_name": self.actor.name,
            },
            channels=[f"cc:{control_center_id}"] if control_center_id else ["broadcast"],
            required_permission=P.AUDIT_READ.value,
        )

    async def commit(self) -> None:
        await self.session.commit()
        pending, self._pending = self._pending, []
        for msg in pending:
            await self.bus.publish(msg)

    async def rollback(self) -> None:
        self._pending.clear()
        await self.session.rollback()


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Field-level change set ``{field: {"old": x, "new": y}}`` for the audit log."""
    return {
        k: {"old": before.get(k), "new": after.get(k)}
        for k in sorted(set(before) | set(after))
        if before.get(k) != after.get(k)
    }


def check_version(entity: Any, expected_version: int, label: str) -> None:
    from app.core.errors import ConflictError

    if entity.version != expected_version:
        raise ConflictError(
            f"{label} wurde zwischenzeitlich von einer anderen Person geändert. Bitte neu laden.",
            details={"current_version": entity.version, "expected_version": expected_version},
        )
