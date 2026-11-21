from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    AuthContext,
    SettingsDep,
    UowDep,
    client_ip,
    get_auth_allow_password_change,
)
from app.core.permissions import P
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ControlCenterRef,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.services.auth_service import AuthService, IssuedTokens

router = APIRouter(prefix="/auth", tags=["Anmeldung"])

PendingAuthDep = Annotated[AuthContext, Depends(get_auth_allow_password_change)]


def me_response(user: User, session_id) -> MeResponse:  # type: ignore[no-untyped-def]
    perms = user.effective_permissions()
    return MeResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        must_change_password=user.must_change_password,
        roles=sorted(r.key for r in user.roles),
        permissions=sorted(perms),
        control_centers=[
            ControlCenterRef.model_validate(cc) for cc in sorted(user.control_centers, key=lambda c: c.name)
        ],
        all_control_centers=P.SYSTEM_ADMIN.value in perms,
        session_id=session_id,
    )


def _token_response(t: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=t.access_token,
        access_token_expires_at=t.access_expires_at,
        refresh_token=t.refresh_token,
        user=me_response(t.user, t.session.id),
    )


@router.post("/login", response_model=TokenResponse, summary="Anmelden")
async def login(body: LoginRequest, request: Request, uow: UowDep, settings: SettingsDep) -> TokenResponse:
    tokens = await AuthService(uow, settings).login(
        body.username, body.password, body.client, client_ip(request, settings)
    )
    return _token_response(tokens)


@router.post("/refresh", response_model=TokenResponse, summary="Token erneuern (Rotation)")
async def refresh(
    body: RefreshRequest, request: Request, uow: UowDep, settings: SettingsDep
) -> TokenResponse:
    tokens = await AuthService(uow, settings).refresh(body.refresh_token, client_ip(request, settings))
    return _token_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Abmelden")
async def logout(auth: PendingAuthDep, request: Request, uow: UowDep, settings: SettingsDep) -> None:
    await AuthService(uow, settings).logout(auth.user, auth.session_id, client_ip(request, settings))


@router.get("/me", response_model=MeResponse, summary="Eigenes Profil und Berechtigungen")
async def me(auth: PendingAuthDep) -> MeResponse:
    return me_response(auth.user, auth.session_id)


@router.post("/change-password", response_model=TokenResponse, summary="Eigenes Passwort ändern")
async def change_password(
    body: ChangePasswordRequest, auth: PendingAuthDep, uow: UowDep, settings: SettingsDep
) -> TokenResponse:
    tokens = await AuthService(uow, settings).change_password(
        auth.user, auth.session_id, body.current_password, body.new_password
    )
    return _token_response(tokens)
