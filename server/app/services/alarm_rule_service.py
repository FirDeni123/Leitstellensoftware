"""Alarm rules (Alarm- und Ausrückeordnung, AAO) per control centre, keyword and optional area.

An AAO only describes what *should* be alarmed. It never triggers anything by itself: the
alarm preview turns it into a proposal and the dispatcher confirms (or changes) it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models import (
    AlarmGroup,
    AlarmRule,
    AlarmRuleItem,
    ControlCenterArea,
    Interface,
    Keyword,
    Ric,
    Station,
    Vehicle,
    VehicleType,
)
from app.services.uow import UnitOfWork, check_version

KIND_COLUMN = {
    "vehicle_type": ("vehicle_type_id", VehicleType),
    "vehicle": ("vehicle_id", Vehicle),
    "station": ("station_id", Station),
    "ric": ("ric_id", Ric),
    "alarm_group": ("alarm_group_id", AlarmGroup),
    "interface": ("interface_id", Interface),
}
KIND_LABEL = {
    "vehicle_type": "Fahrzeugtyp",
    "vehicle": "Fahrzeug",
    "station": "Wache",
    "ric": "RIC",
    "alarm_group": "Alarmierungsgruppe",
    "interface": "Schnittstelle",
}


def item_target_id(item: AlarmRuleItem) -> uuid.UUID:
    value = getattr(item, KIND_COLUMN[item.kind][0])
    assert value is not None
    return value


def target_label(kind: str, target: Any) -> str:
    if kind == "vehicle_type":
        return f"{target.code} – {target.name}"
    if kind == "vehicle":
        return target.call_sign
    if kind == "station":
        return target.name
    if kind == "ric":
        sub = f"/{target.sub_address}" if target.sub_address else ""
        return f"{target.code}{sub} {target.label}"
    return target.name


class AlarmRuleService:
    def __init__(self, uow: UnitOfWork, visible: set[uuid.UUID] | None) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible

    def _check_cc(self, cc_id: uuid.UUID) -> None:
        if self.visible is not None and cc_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")

    def _emit(self, rule: AlarmRule, action: str) -> None:
        self.uow.emit(
            "master_data.changed",
            {"collection": "alarm-rules", "id": str(rule.id), "action": action},
            channels=[f"cc:{rule.control_center_id}"],
        )

    async def get(self, rule_id: uuid.UUID) -> AlarmRule:
        rule = await self.s.get(AlarmRule, rule_id)
        if rule is None:
            raise NotFoundError("Alarmierungsregel nicht gefunden")
        self._check_cc(rule.control_center_id)
        return rule

    async def list(
        self, control_center_id: uuid.UUID | None, keyword_id: uuid.UUID | None
    ) -> list[AlarmRule]:
        stmt = select(AlarmRule).join(Keyword, Keyword.id == AlarmRule.keyword_id)
        if control_center_id:
            self._check_cc(control_center_id)
            stmt = stmt.where(AlarmRule.control_center_id == control_center_id)
        elif self.visible is not None:
            stmt = stmt.where(AlarmRule.control_center_id.in_(self.visible or {uuid.uuid4()}))
        if keyword_id:
            stmt = stmt.where(AlarmRule.keyword_id == keyword_id)
        stmt = stmt.order_by(Keyword.code, AlarmRule.area_id.nulls_first())
        return list((await self.s.scalars(stmt)).all())

    async def labels(self, rules: list[AlarmRule]) -> dict[tuple[str, uuid.UUID], str]:
        """Display labels of all item targets (one query per kind)."""
        wanted: dict[str, set[uuid.UUID]] = {}
        for rule in rules:
            for item in rule.items:
                wanted.setdefault(item.kind, set()).add(item_target_id(item))
        result: dict[tuple[str, uuid.UUID], str] = {}
        for kind, ids in wanted.items():
            model = KIND_COLUMN[kind][1]
            for row in (await self.s.scalars(select(model).where(model.id.in_(ids)))).all():
                result[(kind, row.id)] = target_label(kind, row)
        return result

    async def area_names(self, rules: list[AlarmRule]) -> dict[uuid.UUID, str]:
        ids = {r.area_id for r in rules if r.area_id}
        if not ids:
            return {}
        rows = (await self.s.scalars(select(ControlCenterArea).where(ControlCenterArea.id.in_(ids)))).all()
        return {a.id: a.name for a in rows}

    async def _validate_items(self, cc_id: uuid.UUID, items: list[dict[str, Any]]) -> list[AlarmRuleItem]:
        result: list[AlarmRuleItem] = []
        seen: set[tuple[int, str, uuid.UUID]] = set()
        for position, raw in enumerate(items):
            kind = raw["kind"]
            column, model = KIND_COLUMN[kind]
            target = await self.s.get(model, raw["target_id"])
            if target is None:
                raise ValidationFailedError(f"{KIND_LABEL[kind]} in Zeile {position + 1} nicht gefunden")
            target_cc = getattr(target, "control_center_id", None)
            if kind != "vehicle_type" and target_cc is not None and target_cc != cc_id:
                raise ValidationFailedError(
                    f"{KIND_LABEL[kind]} „{target_label(kind, target)}“ gehört zu einer anderen Leitstelle"
                )
            organization = getattr(target, "organization", None)
            if organization is not None and not organization.alarmable:
                raise ValidationFailedError(
                    f"{target_label(kind, target)}: {organization.name} ist nicht alarmierbar "
                    "(die Polizei wird nie durch das System alarmiert)"
                )
            key = (raw["stage"], kind, target.id)
            if key in seen:
                raise ValidationFailedError(
                    f"„{target_label(kind, target)}“ ist in Stufe {raw['stage']} doppelt eingetragen"
                )
            seen.add(key)
            item = AlarmRuleItem(
                stage=raw["stage"],
                position=position,
                kind=kind,
                count=raw["count"] if kind == "vehicle_type" else 1,
                note=raw.get("note"),
            )
            setattr(item, column, target.id)
            result.append(item)
        return result

    async def create(self, data: dict[str, Any]) -> AlarmRule:
        cc_id = data["control_center_id"]
        self._check_cc(cc_id)
        keyword = await self.s.get(Keyword, data["keyword_id"])
        if keyword is None:
            raise ValidationFailedError("Stichwort nicht gefunden")
        if data.get("area_id"):
            area = await self.s.get(ControlCenterArea, data["area_id"])
            if area is None or area.control_center_id != cc_id:
                raise ValidationFailedError(
                    "Zuständigkeitsbereich fehlt oder gehört zu einer anderen Leitstelle"
                )
        rule = AlarmRule(
            id=uuid.uuid4(),
            control_center_id=cc_id,
            keyword_id=keyword.id,
            area_id=data.get("area_id"),
            name=data.get("name"),
            is_active=data.get("is_active", True),
        )
        rule.items = await self._validate_items(cc_id, data.get("items") or [])
        self.s.add(rule)
        self.uow.audit(
            "create",
            "alarm_rule",
            rule.id,
            f"AAO für {keyword.code} angelegt ({len(rule.items)} Einträge)",
            control_center_id=cc_id,
        )
        self._emit(rule, "created")
        code = keyword.code  # objects are expired after a rollback
        try:
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(
                f"Für {code} existiert in diesem Bereich bereits eine AAO – bitte diese bearbeiten"
            ) from exc
        await self.s.refresh(rule)
        return rule

    async def update(self, rule_id: uuid.UUID, data: dict[str, Any], expected_version: int) -> AlarmRule:
        rule = await self.get(rule_id)
        check_version(rule, expected_version, f"Die AAO für {rule.keyword.code}")
        changes: dict[str, Any] = {}
        for field in ("name", "is_active"):
            if field in data and data[field] is not None and getattr(rule, field) != data[field]:
                changes[field] = {"old": getattr(rule, field), "new": data[field]}
                setattr(rule, field, data[field])
        if data.get("items") is not None:
            old = [(i.stage, i.kind, str(item_target_id(i)), i.count) for i in rule.items]
            new_items = await self._validate_items(rule.control_center_id, data["items"])
            new = [(i.stage, i.kind, str(item_target_id(i)), i.count) for i in new_items]
            if old != new or [i.note for i in rule.items] != [i.note for i in new_items]:
                changes["items"] = {"old": old, "new": new}
                rule.items.clear()
                await self.s.flush()
                rule.items.extend(new_items)
        if not changes:
            return rule
        from datetime import UTC, datetime

        rule.updated_at = datetime.now(UTC)  # also bumps the version when only items changed
        self.uow.audit(
            "update",
            "alarm_rule",
            rule.id,
            f"AAO für {rule.keyword.code} geändert",
            changes=changes,
            control_center_id=rule.control_center_id,
        )
        self._emit(rule, "updated")
        await self.uow.commit()
        await self.s.refresh(rule)
        return rule

    async def delete(self, rule_id: uuid.UUID, expected_version: int) -> None:
        rule = await self.get(rule_id)
        check_version(rule, expected_version, f"Die AAO für {rule.keyword.code}")
        code = rule.keyword.code
        await self.s.delete(rule)
        self.uow.audit(
            "delete",
            "alarm_rule",
            rule_id,
            f"AAO für {code} gelöscht",
            control_center_id=rule.control_center_id,
        )
        self._emit(rule, "deleted")
        await self.uow.commit()
