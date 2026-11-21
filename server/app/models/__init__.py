"""All ORM models – imported here so Alembic and the metadata see every table."""

from app.models.alarming import (
    Alarm,
    AlarmRule,
    AlarmRuleItem,
    AlarmTarget,
    Interface,
    InterfaceEvent,
    PoliceNotice,
)
from app.models.audit import AuditLog
from app.models.auth import AuthSession, LoginEvent, RefreshToken
from app.models.control_center import ControlCenter, ControlCenterArea, ControlCenterLink
from app.models.imports import ImportJob
from app.models.master_data import (
    AlarmGroup,
    Organization,
    RadioGroup,
    Ric,
    Station,
    Vehicle,
    VehicleStatusDefinition,
    VehicleType,
)
from app.models.operations import (
    CallNote,
    EmergencyCall,
    Incident,
    IncidentEvent,
    IncidentNumberSequence,
    IncidentVehicle,
    Keyword,
)
from app.models.settings import OperationMode, SystemSetting, UserLayout
from app.models.user import (
    Permission,
    PermissionEffect,
    Role,
    User,
    UserPermissionOverride,
    role_permissions,
    user_control_centers,
    user_roles,
)

__all__ = [
    "Alarm",
    "AlarmRule",
    "AlarmRuleItem",
    "AlarmTarget",
    "Interface",
    "InterfaceEvent",
    "PoliceNotice",
    "CallNote",
    "EmergencyCall",
    "Incident",
    "IncidentEvent",
    "IncidentNumberSequence",
    "IncidentVehicle",
    "Keyword",
    "AlarmGroup",
    "ControlCenterArea",
    "ControlCenterLink",
    "ImportJob",
    "Organization",
    "RadioGroup",
    "Ric",
    "Station",
    "Vehicle",
    "VehicleStatusDefinition",
    "VehicleType",
    "AuditLog",
    "AuthSession",
    "ControlCenter",
    "LoginEvent",
    "OperationMode",
    "Permission",
    "PermissionEffect",
    "RefreshToken",
    "Role",
    "SystemSetting",
    "User",
    "UserLayout",
    "UserPermissionOverride",
    "role_permissions",
    "user_control_centers",
    "user_roles",
]
