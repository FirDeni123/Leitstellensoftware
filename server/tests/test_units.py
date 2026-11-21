"""Unit tests without database: security primitives, encryption, event routing."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Environment, Settings
from app.core.crypto import SecretBox, SecretBoxError
from app.core.errors import AuthenticationError, ValidationFailedError
from app.core.permissions import ALL_PERMISSIONS, CATALOGUE, DEFAULT_ROLES
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_initial_password,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.realtime.bus import BusMessage, InMemoryEventBus
from app.realtime.hub import Connection

S = Settings(environment=Environment.TEST)


def test_password_hashing():
    h = hash_password("Richtig-Horse-42")
    assert h.startswith("$argon2id$")
    assert verify_password("Richtig-Horse-42", h)
    assert not verify_password("falsch", h)
    assert not verify_password("egal", None)
    assert not verify_password("egal", "kein-hash")


@pytest.mark.parametrize("pw", ["kurz1!", "nurkleinbuchstaben", "alllowercase1234", "dispo-Passwort-1"])
def test_password_policy_rejects(pw):
    with pytest.raises(ValidationFailedError):
        validate_password_policy(pw, S, username="dispo")


def test_generated_passwords_satisfy_policy():
    for _ in range(50):
        validate_password_policy(generate_initial_password(username="dispo"), S, username="dispo")


def test_access_token_roundtrip_and_tampering():
    uid, sid = uuid.uuid4(), uuid.uuid4()
    token, _ = create_access_token(S, user_id=uid, session_id=sid, token_version=3)
    claims = decode_access_token(S, token)
    assert (claims.user_id, claims.session_id, claims.token_version) == (uid, sid, 3)
    other = Settings(environment=Environment.TEST, jwt_secret="x" * 40)
    with pytest.raises(AuthenticationError):
        decode_access_token(other, token)


def test_expired_token_rejected():
    payload = {
        "iss": S.jwt_issuer,
        "sub": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "tv": 1,
        "typ": "access",
        "exp": int((datetime.now(UTC) - timedelta(seconds=5)).timestamp()),
    }
    token = jwt.encode(payload, S.jwt_secret, algorithm="HS256")
    with pytest.raises(AuthenticationError) as exc:
        decode_access_token(S, token)
    assert exc.value.details["reason"] == "token_expired"


def test_production_rejects_insecure_defaults():
    with pytest.raises(ValueError, match="Unsichere Produktionskonfiguration"):
        Settings(environment=Environment.PRODUCTION)


def test_secret_box_roundtrip_rotation_and_wrong_key():
    k1, k2 = SecretBox.generate_key(), SecretBox.generate_key()
    old = SecretBox([k1])
    token = old.encrypt("api-key-123456")
    assert "api-key" not in token
    rotated_box = SecretBox([k2, k1])  # new primary key, old key still decrypts
    assert rotated_box.decrypt(token) == "api-key-123456"
    new_token = rotated_box.rotate(token)
    assert SecretBox([k2]).decrypt(new_token) == "api-key-123456"
    with pytest.raises(SecretBoxError):
        SecretBox([k2]).decrypt(token)
    with pytest.raises(SecretBoxError):
        SecretBox(["kein-gueltiger-schluessel"])
    assert SecretBox.mask("api-key-123456") == "••••3456"


def test_permission_catalogue_consistency():
    codes = [p.code.value for p in CATALOGUE]
    assert len(codes) == len(set(codes))
    for role in DEFAULT_ROLES:
        assert role.permissions <= ALL_PERMISSIONS
    admin = next(r for r in DEFAULT_ROLES if r.key == "admin")
    assert admin.permissions == ALL_PERMISSIONS
    # Only administrators may activate real interfaces or change the operation mode.
    for role in DEFAULT_ROLES:
        if role.key != "admin":
            assert "interfaces.activate_real" not in role.permissions
            assert "system.mode.change" not in role.permissions


def _conn(perms=frozenset(), channels=None, all_cc=False):
    return Connection(
        websocket=None,
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),  # type: ignore[arg-type]
        permissions=frozenset(perms),
        channels=set(channels or []),
        all_control_centers=all_cc,
        token_expires_at=datetime.now(UTC),
    )


def test_connection_event_filtering():
    cc = uuid.uuid4()
    dispo = _conn(channels={f"cc:{cc}"})
    other = _conn(channels={f"cc:{uuid.uuid4()}"})
    admin = _conn(perms={"users.read"}, all_cc=True)
    msg_cc = BusMessage(kind="event", topic="x", data={}, channels=[f"cc:{cc}"])
    assert dispo.accepts(msg_cc) and admin.accepts(msg_cc) and not other.accepts(msg_cc)
    msg_perm = BusMessage(kind="event", topic="user.updated", data={}, required_permission="users.read")
    assert admin.accepts(msg_perm) and not dispo.accepts(msg_perm)


def test_bus_message_json_roundtrip():
    msg = BusMessage(kind="event", topic="t", data={"a": 1}, channels=["user:1"], required_permission="p")
    assert BusMessage.from_json(msg.to_json()) == msg


async def test_in_memory_bus_delivers():
    bus = InMemoryEventBus()
    received: list[BusMessage] = []

    async def handler(m: BusMessage) -> None:
        received.append(m)

    await bus.start(handler)
    await bus.publish(BusMessage(kind="event", topic="t", data={}))
    await asyncio.sleep(0)
    assert [m.topic for m in received] == ["t"]


def test_geometry_validation_and_point_in_polygon():
    from app.core.errors import ValidationFailedError
    from app.core.geo import haversine_m, normalise_geometry, point_in_geometry

    square = normalise_geometry(
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[10.0, 53.0], [11.0, 53.0], [11.0, 54.0], [10.0, 54.0]]],
            },
        }
    )
    assert square["type"] == "MultiPolygon"
    assert square["coordinates"][0][0][0] == square["coordinates"][0][0][-1]  # ring closed automatically
    assert point_in_geometry(53.5, 10.5, square)
    assert not point_in_geometry(54.5, 10.5, square)
    for bad in (
        {"type": "Point", "coordinates": [10, 53]},
        {"type": "Polygon", "coordinates": [[[10, 53], [11, 53]]]},
        {"type": "Polygon", "coordinates": [[[10, 53], [11, 53], [11, 95]]]},
        "kein geojson",
    ):
        with pytest.raises(ValidationFailedError):
            normalise_geometry(bad)
    # Schwarzenbek -> Hamburg Rathaus ~ 29 km
    assert 28_000 < haversine_m(53.5036, 10.4806, 53.5503, 9.9920) < 34_000
