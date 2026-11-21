from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin
from app.models.control_center import ControlCenter

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_code", String(64), ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    ),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
)

user_control_centers = Table(
    "user_control_centers",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "control_center_id",
        UUID(as_uuid=True),
        ForeignKey("control_centers.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    area: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    # System roles (shipped defaults) can be edited but not deleted.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions, lazy="selectin")


class PermissionEffect(StrEnum):
    GRANT = "grant"
    DENY = "deny"


class UserPermissionOverride(Base):
    """Individual permission adjustment on top of the user's roles (deny wins)."""

    __tablename__ = "user_permission_overrides"
    __table_args__ = (UniqueConstraint("user_id", "permission_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code", ondelete="CASCADE"))
    effect: Mapped[PermissionEffect] = mapped_column(
        Enum(PermissionEffect, name="permission_effect", values_callable=lambda e: [m.value for m in e])
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column()
    last_login_at: Mapped[datetime | None] = mapped_column()
    password_changed_at: Mapped[datetime | None] = mapped_column()
    # Incremented on password change / deactivation -> invalidates all access tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=1)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")
    control_centers: Mapped[list[ControlCenter]] = relationship(
        secondary=user_control_centers, lazy="selectin"
    )
    permission_overrides: Mapped[list[UserPermissionOverride]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )

    def effective_permissions(self) -> set[str]:
        perms = {p.code for role in self.roles for p in role.permissions}
        for o in self.permission_overrides:
            if o.effect == PermissionEffect.GRANT:
                perms.add(o.permission_code)
        for o in self.permission_overrides:
            if o.effect == PermissionEffect.DENY:
                perms.discard(o.permission_code)
        return perms
