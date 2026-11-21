"""Two bus instances (= two API servers) exchange events through Redis."""

from __future__ import annotations

import asyncio
import os

import pytest

from app.realtime.bus import BusMessage, RedisEventBus

REDIS_URL = os.environ.get("ILS_TEST_REDIS_URL", "redis://localhost:6379/15")


async def test_events_cross_server_instances():
    probe = RedisEventBus(REDIS_URL)
    if not await probe.ping():
        await probe.stop()
        pytest.skip("Redis nicht erreichbar")
    await probe.stop()

    received_a: list[str] = []
    received_b: list[str] = []
    a, b = RedisEventBus(REDIS_URL), RedisEventBus(REDIS_URL)

    async def on_a(m: BusMessage) -> None:
        received_a.append(m.topic)

    async def on_b(m: BusMessage) -> None:
        received_b.append(m.topic)

    await a.start(on_a)
    await b.start(on_b)
    await asyncio.sleep(0.2)  # let subscriptions settle
    try:
        await a.publish(BusMessage(kind="event", topic="vehicle.status", data={"status": 3}))
        for _ in range(50):
            if received_a and received_b:
                break
            await asyncio.sleep(0.05)
        assert received_a == ["vehicle.status"] and received_b == ["vehicle.status"]
    finally:
        await a.stop()
        await b.stop()
