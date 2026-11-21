"""ils-admin: demo data are refused on production servers unless explicitly allowed."""

from __future__ import annotations

import pytest

from app import cli


def test_seed_demo_refused_in_production_without_flag(monkeypatch):
    calls: list[str] = []

    async def fake_seed(password: str) -> None:
        calls.append(password)

    monkeypatch.setattr(cli, "seed_demo", fake_seed)
    monkeypatch.setattr(cli, "get_settings", lambda: type("S", (), {"is_production": True})())
    with pytest.raises(SystemExit, match="--allow-production"):
        cli.main(["seed-demo"])
    assert calls == []
    cli.main(["seed-demo", "--allow-production", "--password", "Test-Pass-2026!"])
    assert calls == ["Test-Pass-2026!"]
