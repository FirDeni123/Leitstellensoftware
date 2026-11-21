from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.api.deps import AuthContext, SettingsDep, UowDep, require, uow_for
from app.core.permissions import P
from app.models import LoginEvent
from app.schemas.common import Page
from app.schemas.users import (
    LoginEventOut,
    PasswordResetRequest,
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    UserActiveUpdate,
    UserCreate,
    UserCreatedResponse,
    UserOut,
    UserUpdate,
)
from app.services.role_service import RoleService, role_out
from app.services.user_service import UserService, user_out

router = APIRouter(tags=["Benutzer und Rollen"])

CanRead = Annotated[AuthContext, Depends(require(P.USERS_READ))]
CanWrite = Annotated[AuthContext, Depends(require(P.USERS_READ, P.USERS_WRITE))]
CanRoles = Annotated[AuthContext, Depends(require(P.ROLES_WRITE))]


# ----------------------------------------------------------------------------------- users
@router.get("/users", response_model=Page[UserOut], summary="Benutzer auflisten")
async def list_users(
    auth: CanRead,
    uow: UowDep,
    settings: SettingsDep,
    q: str | None = Query(default=None, max_length=100),
    active: bool | None = None,
    control_center_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Page[UserOut]:
    users, total = await UserService(uow, settings).list(
        q=q, active=active, control_center_id=control_center_id, limit=limit, offset=offset
    )
    return Page(items=[user_out(u) for u in users], total=total)


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, auth: CanRead, uow: UowDep, settings: SettingsDep) -> UserOut:
    return user_out(await UserService(uow, settings).get(user_id))


@router.post("/users", response_model=UserCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, auth: CanWrite, uow: UowDep, settings: SettingsDep
) -> UserCreatedResponse:
    user, generated = await UserService(uow_for(auth, uow), settings).create(body)
    return UserCreatedResponse(user=user_out(user), initial_password=generated)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, auth: CanWrite, uow: UowDep, settings: SettingsDep
) -> UserOut:
    if (body.roles is not None or body.permission_overrides is not None) and not auth.has(P.ROLES_WRITE):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Rollen/Berechtigungen ändern erfordert 'roles.write'")
    return user_out(await UserService(uow_for(auth, uow), settings).update(user_id, body))


@router.put("/users/{user_id}/active", response_model=UserOut, summary="Benutzer (de)aktivieren")
async def set_user_active(
    user_id: uuid.UUID, body: UserActiveUpdate, auth: CanWrite, uow: UowDep, settings: SettingsDep
) -> UserOut:
    user = await UserService(uow_for(auth, uow), settings).set_active(
        user_id, body.is_active, body.expected_version, auth.user.id
    )
    return user_out(user)


@router.post("/users/{user_id}/reset-password", response_model=UserCreatedResponse)
async def reset_password(
    user_id: uuid.UUID, body: PasswordResetRequest, auth: CanWrite, uow: UowDep, settings: SettingsDep
) -> UserCreatedResponse:
    user, generated = await UserService(uow_for(auth, uow), settings).reset_password(
        user_id, body.new_password, body.expected_version
    )
    return UserCreatedResponse(user=user_out(user), initial_password=generated)


@router.post("/users/{user_id}/unlock", response_model=UserOut, summary="Anmeldesperre aufheben")
async def unlock_user(user_id: uuid.UUID, auth: CanWrite, uow: UowDep, settings: SettingsDep) -> UserOut:
    return user_out(await UserService(uow_for(auth, uow), settings).unlock(user_id))


@router.get("/login-events", response_model=list[LoginEventOut], summary="Anmeldeprotokoll")
async def login_events(
    auth: Annotated[AuthContext, Depends(require(P.LOGIN_LOG_READ))],
    uow: UowDep,
    username: str | None = None,
    success: bool | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    before_id: int | None = None,
) -> list[LoginEventOut]:
    stmt = select(LoginEvent).order_by(LoginEvent.id.desc()).limit(limit)
    if username:
        stmt = stmt.where(LoginEvent.username == username.lower())
    if success is not None:
        stmt = stmt.where(LoginEvent.success.is_(success))
    if before_id:
        stmt = stmt.where(LoginEvent.id < before_id)
    return [LoginEventOut.model_validate(e) for e in (await uow.session.scalars(stmt)).all()]


# ----------------------------------------------------------------------------------- roles
@router.get("/permissions", response_model=list[PermissionOut], summary="Berechtigungskatalog")
async def list_permissions(auth: CanRead, uow: UowDep) -> list[PermissionOut]:
    return [PermissionOut.model_validate(p) for p in await RoleService(uow).permissions()]


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(auth: CanRead, uow: UowDep) -> list[RoleOut]:
    return [role_out(r) for r in await RoleService(uow).list()]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(body: RoleCreate, auth: CanRoles, uow: UowDep) -> RoleOut:
    return role_out(await RoleService(uow_for(auth, uow)).create(body))


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(role_id: uuid.UUID, body: RoleUpdate, auth: CanRoles, uow: UowDep) -> RoleOut:
    return role_out(await RoleService(uow_for(auth, uow)).update(role_id, body))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: uuid.UUID, auth: CanRoles, uow: UowDep) -> None:
    await RoleService(uow_for(auth, uow)).delete(role_id)
