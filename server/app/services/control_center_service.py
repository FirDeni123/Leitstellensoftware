"""Control centres (Leitstellen) – the tenants of the system."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.models import ControlCenter
from app.schemas.control_centers import ControlCenterCreate, ControlCenterUpdate
from app.services.uow import UnitOfWork, check_version, diff

_FIELDS = ("name", "description", "address", "latitude", "longitude", "is_active")


def _snapshot(cc: ControlCenter) -> dict[str, Any]:
    return {f: getattr(cc, f) for f in ("code", *_FIELDS)}


class ControlCenterService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.s = uow.session

    async def list(self, visible_ids: set[uuid.UUID] | None) -> list[ControlCenter]:
        """``visible_ids=None`` means unrestricted (administrators)."""
        stmt = select(ControlCenter).order_by(ControlCenter.name)
        if visible_ids is not None:
            if not visible_ids:
                return []
            stmt = stmt.where(ControlCenter.id.in_(visible_ids))
        return list((await self.s.scalars(stmt)).all())

    async def get(self, cc_id: uuid.UUID, visible_ids: set[uuid.UUID] | None = None) -> ControlCenter:
        cc = await self.s.get(ControlCenter, cc_id)
        if cc is None:
            raise NotFoundError("Leitstelle nicht gefunden")
        if visible_ids is not None and cc.id not in visible_ids:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")
        return cc

    async def create(self, data: ControlCenterCreate) -> ControlCenter:
        cc = ControlCenter(**data.model_dump())
        self.s.add(cc)
        try:
            await self.s.flush()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(f"Kennung '{data.code}' ist bereits vergeben") from exc
        self.uow.audit(
            "create",
            "control_center",
            cc.id,
            f"Leitstelle {cc.name} angelegt",
            changes=diff({}, _snapshot(cc)),
            control_center_id=cc.id,
        )
        self.uow.emit("control_center.changed", {"id": str(cc.id)})
        await self.uow.commit()
        return cc

    async def update(self, cc_id: uuid.UUID, data: ControlCenterUpdate) -> ControlCenter:
        cc = await self.get(cc_id)
        check_version(cc, data.expected_version, "Die Leitstelle")
        before = _snapshot(cc)
        for field in _FIELDS:
            if field in data.model_fields_set:
                value = getattr(data, field)
                if value is None and field in ("name", "is_active"):
                    continue
                setattr(cc, field, value)
        changes = diff(before, _snapshot(cc))
        if not changes:
            return cc
        await self.s.flush()
        self.uow.audit(
            "update",
            "control_center",
            cc.id,
            f"Leitstelle {cc.name} geändert",
            changes=changes,
            control_center_id=cc.id,
        )
        self.uow.emit("control_center.changed", {"id": str(cc.id)})
        await self.uow.commit()
        return cc

    async def delete(self, cc_id: uuid.UUID) -> None:
        cc = await self.get(cc_id)
        name = cc.name
        try:
            await self.s.delete(cc)
            await self.s.flush()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError("Leitstelle hat noch abhängige Daten und kann nicht gelöscht werden") from exc
        self.uow.audit("delete", "control_center", cc_id, f"Leitstelle {name} gelöscht")
        self.uow.emit("control_center.changed", {"id": str(cc_id), "deleted": True})
        await self.uow.commit()
