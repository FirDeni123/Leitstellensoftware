"""Event bus: decouples producers (services, simulation) from WebSocket delivery.

* ``InMemoryEventBus`` – single server process (development, tests).
* ``RedisEventBus`` – several API instances and the separate simulation service share
  one Redis Pub/Sub channel, so every connected dispatcher sees the same events no matter
  which instance they are connected to.

Messages are JSON documents; see :class:`BusMessage`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

REDIS_CHANNEL = "ils:bus"


@dataclass(slots=True)
class BusMessage:
    """``kind='event'`` is delivered to clients; ``kind='control'`` is handled by the hubs."""

    kind: Literal["event", "control"]
    topic: str
    data: dict[str, Any]
    # Delivery scope (OR): "broadcast", "user:<id>", "cc:<id>".
    channels: list[str] = field(default_factory=lambda: ["broadcast"])
    # Additional AND condition: only connections whose user holds this permission.
    required_permission: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, raw: str | bytes) -> BusMessage:
        return cls(**json.loads(raw))


Handler = Callable[[BusMessage], Awaitable[None]]


class EventBus(Protocol):
    name: Literal["memory", "redis"]

    async def start(self, handler: Handler) -> None: ...
    async def publish(self, message: BusMessage) -> None: ...
    async def stop(self) -> None: ...


class InMemoryEventBus:
    name: Literal["memory", "redis"] = "memory"

    def __init__(self) -> None:
        self._handler: Handler | None = None

    async def start(self, handler: Handler) -> None:
        self._handler = handler

    async def publish(self, message: BusMessage) -> None:
        if self._handler is not None:
            await self._handler(message)

    async def stop(self) -> None:
        self._handler = None


class RedisEventBus:
    name: Literal["memory", "redis"] = "redis"

    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url)
        self._task: asyncio.Task[None] | None = None

    async def start(self, handler: Handler) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL)
        self._task = asyncio.create_task(self._listen(pubsub, handler), name="redis-bus-listener")

    async def _listen(self, pubsub: Any, handler: Handler) -> None:
        backoff = 1.0
        while True:
            try:
                async for raw in pubsub.listen():
                    if raw.get("type") != "message":
                        continue
                    try:
                        await handler(BusMessage.from_json(raw["data"]))
                    except Exception:
                        logger.exception("Event handler failed")
                    backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                # Automatic reconnection to Redis with exponential backoff.
                logger.exception("Redis-Verbindung verloren, neuer Versuch in %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                with contextlib.suppress(Exception):
                    await pubsub.subscribe(REDIS_CHANNEL)

    async def publish(self, message: BusMessage) -> None:
        await self._redis.publish(REDIS_CHANNEL, message.to_json())

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._redis.aclose()


def create_bus(redis_url: str | None) -> EventBus:
    return RedisEventBus(redis_url) if redis_url else InMemoryEventBus()
