"""Router factory for master data CRUD endpoints.

Note: this module deliberately does not use ``from __future__ import annotations`` –
FastAPI must see the concrete (dynamically chosen) schema classes in the signatures.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.errors import ValidationFailedError
from app.core.permissions import P
from app.services.crud import CrudService, CrudSpec


def visible_control_centers(auth: AuthContext) -> set[uuid.UUID] | None:
    return None if auth.is_admin else auth.control_center_ids()


def _filters(request: Request, allowed: dict[str, Callable[[str], Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, parse in allowed.items():
        raw = request.query_params.get(name)
        if raw is None or raw == "":
            continue
        try:
            result[name] = parse(raw)
        except ValueError as exc:
            raise ValidationFailedError(f"Ungültiger Filter {name}") from exc
    return result


def register_crud(
    router: APIRouter,
    *,
    spec: CrudSpec,
    path: str,
    create_model: type[BaseModel] | None,
    update_model: type[BaseModel],
    out_model: type[BaseModel],
    read_perm: P,
    write_perm: P,
    to_out: Callable[[Any], BaseModel] | None = None,
    filters: dict[str, Callable[[str], Any]] | None = None,
    id_type: type = uuid.UUID,
    allow_delete: bool = True,
) -> None:
    convert = to_out or out_model.model_validate
    read_dep = Annotated[AuthContext, Depends(require(read_perm))]
    write_dep = Annotated[AuthContext, Depends(require(read_perm, write_perm))]
    tag = spec.label
    allowed_filters = filters or {}

    @router.get(path, response_model=list[out_model], summary=f"{spec.label}: Liste", tags=[tag])
    async def list_items(
        request: Request,
        auth: read_dep,
        uow: UowDep,
        control_center_id: uuid.UUID | None = None,
        q: str | None = Query(default=None, max_length=100),
    ) -> Any:
        service = CrudService(spec, uow, visible_control_centers(auth))
        items = await service.list(
            control_center_id=control_center_id, q=q, filters=_filters(request, allowed_filters)
        )
        return [convert(i) for i in items]

    @router.get(f"{path}/{{item_id}}", response_model=out_model, summary=f"{spec.label}: Abrufen", tags=[tag])
    async def get_item(item_id: id_type, auth: read_dep, uow: UowDep) -> Any:  # type: ignore[valid-type]
        return convert(await CrudService(spec, uow, visible_control_centers(auth)).get(item_id))

    if create_model is not None:

        @router.post(
            path,
            response_model=out_model,
            status_code=status.HTTP_201_CREATED,
            summary=f"{spec.label}: Anlegen",
            tags=[tag],
        )
        async def create_item(body: create_model, auth: write_dep, uow: UowDep) -> Any:  # type: ignore[valid-type]
            service = CrudService(spec, uow_for(auth, uow), visible_control_centers(auth))
            return convert(await service.create(body.model_dump()))

    @router.patch(
        f"{path}/{{item_id}}", response_model=out_model, summary=f"{spec.label}: Ändern", tags=[tag]
    )
    async def update_item(item_id: id_type, body: update_model, auth: write_dep, uow: UowDep) -> Any:  # type: ignore[valid-type]
        data = body.model_dump(exclude_unset=True, exclude={"expected_version"})
        service = CrudService(spec, uow_for(auth, uow), visible_control_centers(auth))
        return convert(await service.update(item_id, data, body.expected_version))

    if allow_delete:

        @router.delete(
            f"{path}/{{item_id}}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary=f"{spec.label}: Löschen",
            tags=[tag],
        )
        async def delete_item(item_id: id_type, auth: write_dep, uow: UowDep) -> None:  # type: ignore[valid-type]
            await CrudService(spec, uow_for(auth, uow), visible_control_centers(auth)).delete(item_id)
