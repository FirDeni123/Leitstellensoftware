"""Generic create/read/update/delete for master data.

One :class:`CrudSpec` per entity describes fields, references and relations. The service
then provides – identically for every entity – tenant scoping, optimistic locking,
referential checks (same control centre), readable conflict messages, field-level audit
entries and realtime events. New master data types need a spec, not new plumbing.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, cast, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.services.uow import UnitOfWork, check_version, diff

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
CHECK_VIOLATION = "23514"


def sqlstate(exc: IntegrityError) -> str | None:
    orig = exc.orig
    for candidate in (orig, getattr(orig, "__cause__", None)):
        code = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if code:
            return str(code)
    return None


@dataclass(frozen=True, slots=True)
class Ref:
    """A foreign key field in the payload (e.g. ``station_id``)."""

    field: str
    model: type
    label: str
    scoped: bool = True  # target must belong to the same control centre


@dataclass(frozen=True, slots=True)
class Relation:
    """An n:m relationship set by a list of ids in the payload (e.g. ``ric_ids``)."""

    attr: str
    field: str
    model: type
    label: str
    title: Callable[[Any], str]
    scoped: bool = True


Hook = Callable[[AsyncSession, Any, dict[str, Any], bool], Awaitable[None]]


@dataclass(frozen=True)
class CrudSpec:
    model: type
    entity_type: str  # audit entity type, e.g. "station"
    collection: str  # realtime / client cache key, e.g. "stations"
    label: str  # German singular, e.g. "Wache"
    title: Callable[[Any], str]
    fields: tuple[str, ...]  # updatable scalar fields
    create_only: tuple[str, ...] = ()  # set on create only (e.g. code)
    refs: tuple[Ref, ...] = ()
    relations: tuple[Relation, ...] = ()
    scoped: bool = True  # has control_center_id
    search: tuple[str, ...] = ()
    order_by: tuple[str, ...] = ("name",)
    unique_message: str = "existiert bereits"
    in_use_message: str = "wird noch verwendet und kann nicht gelöscht werden"
    # Business rules: (session, obj, payload, is_create) -> raise on violation
    validate: Hook | None = None
    # Defaults derived from other data before validation (e.g. organisation from station)
    prepare: Hook | None = None
    snapshot_extra: Callable[[Any], dict[str, Any]] = field(default=lambda _o: {})


class CrudService:
    def __init__(self, spec: CrudSpec, uow: UnitOfWork, visible_ccs: set[uuid.UUID] | None) -> None:
        """``visible_ccs=None`` means unrestricted (administrators)."""
        self.spec = spec
        self.uow = uow
        self.s = uow.session
        self.visible = visible_ccs

    # ------------------------------------------------------------------------------ helpers
    def _pk(self, obj: Any) -> Any:
        return getattr(obj, self.spec.model.__mapper__.primary_key[0].key)

    def _check_cc(self, cc_id: uuid.UUID) -> None:
        if self.visible is not None and cc_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")

    def snapshot(self, obj: Any) -> dict[str, Any]:
        snap: dict[str, Any] = {
            f: _plain(getattr(obj, f)) for f in (*self.spec.create_only, *self.spec.fields)
        }
        for ref in self.spec.refs:
            snap[ref.field] = _plain(getattr(obj, ref.field))
        for rel in self.spec.relations:
            snap[rel.attr] = sorted(rel.title(t) for t in getattr(obj, rel.attr))
        snap.update(self.spec.snapshot_extra(obj))
        return snap

    def _emit(self, obj_id: Any, cc_id: uuid.UUID | None, action: str) -> None:
        self.uow.emit(
            "master_data.changed",
            {"collection": self.spec.collection, "id": str(obj_id), "action": action},
            channels=[f"cc:{cc_id}"] if cc_id else ["broadcast"],
        )

    async def _resolve_ref(self, ref: Ref, value: uuid.UUID | None, cc_id: uuid.UUID | None) -> None:
        if value is None:
            return
        target = await self.s.get(ref.model, value)
        if target is None:
            raise ValidationFailedError(f"{ref.label} nicht gefunden", details={"field": ref.field})
        if ref.scoped and cc_id is not None and target.control_center_id != cc_id:
            raise ValidationFailedError(
                f"{ref.label} gehört zu einer anderen Leitstelle", details={"field": ref.field}
            )

    async def _resolve_relation(
        self, rel: Relation, ids: Iterable[uuid.UUID], cc_id: uuid.UUID | None
    ) -> list[Any]:
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return []
        rows = list((await self.s.scalars(select(rel.model).where(rel.model.id.in_(wanted)))).all())
        if len(rows) != len(wanted):
            raise ValidationFailedError(f"{rel.label}: unbekannte Einträge", details={"field": rel.field})
        if rel.scoped and cc_id is not None and any(r.control_center_id != cc_id for r in rows):
            raise ValidationFailedError(
                f"{rel.label}: Einträge einer anderen Leitstelle sind nicht zulässig",
                details={"field": rel.field},
            )
        return rows

    def _not_nullable(self, name: str, value: Any) -> bool:
        column = self.spec.model.__table__.c.get(name)
        if value is None and column is not None and not column.nullable:
            raise ValidationFailedError(f"Feld „{name}“ darf nicht leer sein", details={"field": name})
        return True

    async def _apply(self, obj: Any, data: dict[str, Any], is_create: bool) -> None:
        cc_id = getattr(obj, "control_center_id", None) if self.spec.scoped else None
        for name in (*self.spec.fields, *(self.spec.create_only if is_create else ())):
            if name in data and self._not_nullable(name, data[name]):
                setattr(obj, name, data[name])
        for ref in self.spec.refs:
            if ref.field in data and self._not_nullable(ref.field, data[ref.field]):
                await self._resolve_ref(ref, data[ref.field], cc_id)
                setattr(obj, ref.field, data[ref.field])
        for rel in self.spec.relations:
            if rel.field in data and data[rel.field] is not None:
                setattr(obj, rel.attr, await self._resolve_relation(rel, data[rel.field], cc_id))

    async def _flush(self) -> None:
        try:
            await self.s.flush()
        except IntegrityError as exc:
            await self.uow.rollback()
            code = sqlstate(exc)
            if code == UNIQUE_VIOLATION:
                raise ConflictError(f"{self.spec.label} {self.spec.unique_message}") from exc
            if code == FOREIGN_KEY_VIOLATION:
                raise ConflictError(f"{self.spec.label} {self.spec.in_use_message}") from exc
            if code == CHECK_VIOLATION:
                raise ValidationFailedError(f"{self.spec.label}: unzulässige Werte") from exc
            raise

    # ------------------------------------------------------------------------------ queries
    async def list(
        self,
        *,
        control_center_id: uuid.UUID | None = None,
        q: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[Any]:
        model = self.spec.model
        stmt = select(model)
        if self.spec.scoped:
            if control_center_id is not None:
                self._check_cc(control_center_id)
                stmt = stmt.where(model.control_center_id == control_center_id)
            elif self.visible is not None:
                if not self.visible:
                    return []
                stmt = stmt.where(model.control_center_id.in_(self.visible))
        for name, value in (filters or {}).items():
            if value is not None:
                stmt = stmt.where(getattr(model, name) == value)
        if q and self.spec.search:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(*(cast(getattr(model, f), String).ilike(like) for f in self.spec.search)))
        stmt = stmt.order_by(*(getattr(model, f) for f in self.spec.order_by))
        return list((await self.s.scalars(stmt)).all())

    async def get(self, obj_id: Any) -> Any:
        obj = await self.s.get(self.spec.model, obj_id)
        if obj is None:
            raise NotFoundError(f"{self.spec.label} nicht gefunden")
        if self.spec.scoped:
            self._check_cc(obj.control_center_id)
        return obj

    # ------------------------------------------------------------------------------- writes
    async def create(self, data: dict[str, Any]) -> Any:
        obj = self.spec.model()
        if self.spec.scoped:
            cc_id = data["control_center_id"]
            self._check_cc(cc_id)
            obj.control_center_id = cc_id
        if self.spec.prepare:
            await self.spec.prepare(self.s, obj, data, True)
        await self._apply(obj, data, is_create=True)
        if self.spec.validate:
            await self.spec.validate(self.s, obj, data, True)
        self.s.add(obj)
        await self._flush()
        cc = getattr(obj, "control_center_id", None)
        self.uow.audit(
            "create",
            self.spec.entity_type,
            self._pk(obj),
            f"{self.spec.label} {self.spec.title(obj)} angelegt",
            changes=diff({}, self.snapshot(obj)),
            control_center_id=cc,
        )
        self._emit(self._pk(obj), cc, "created")
        await self.uow.commit()
        await self.s.refresh(obj)  # load relationships of the new row for the response
        return obj

    async def update(self, obj_id: Any, data: dict[str, Any], expected_version: int) -> Any:
        obj = await self.get(obj_id)
        check_version(obj, expected_version, f"{self.spec.label} {self.spec.title(obj)}")
        before = self.snapshot(obj)
        if self.spec.prepare:
            await self.spec.prepare(self.s, obj, data, False)
        await self._apply(obj, data, is_create=False)
        if self.spec.validate:
            await self.spec.validate(self.s, obj, data, False)
        changes = diff(before, self.snapshot(obj))
        if not changes:
            return obj
        if hasattr(obj, "updated_at"):
            obj.updated_at = datetime.now(UTC)  # also bumps the version for relation-only changes
        await self._flush()
        cc = getattr(obj, "control_center_id", None)
        self.uow.audit(
            "update",
            self.spec.entity_type,
            self._pk(obj),
            f"{self.spec.label} {self.spec.title(obj)} geändert",
            changes=changes,
            control_center_id=cc,
        )
        self._emit(self._pk(obj), cc, "updated")
        await self.uow.commit()
        await self.s.refresh(obj)  # FK changes (e.g. station_id) -> reload relationships
        return obj

    async def delete(self, obj_id: Any) -> None:
        obj = await self.get(obj_id)
        title, cc, key = self.spec.title(obj), getattr(obj, "control_center_id", None), self._pk(obj)
        snapshot = self.snapshot(obj)
        await self.s.delete(obj)
        await self._flush()
        self.uow.audit(
            "delete",
            self.spec.entity_type,
            key,
            f"{self.spec.label} {title} gelöscht",
            changes=diff(snapshot, {}),
            control_center_id=cc,
        )
        self._emit(key, cc, "deleted")
        await self.uow.commit()


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
