"""Background runner of the vehicle simulation (1-Hz tick).

Exactly one server process simulates (leader election via a PostgreSQL advisory lock held on
a dedicated connection), so several API workers never move vehicles twice. The runner does
nothing in real operation: real positions will come from position plugins (GPS), never from
the simulation.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import OperationMode
from app.services.uow import Actor, UnitOfWork

logger = logging.getLogger(__name__)
LEADER_LOCK = 470_066
SIMULATION_ACTOR = Actor(None, "Simulation")


async def tick_once(state: Any) -> int:
    """One simulation step; returns the number of moving vehicles. Used by the runner and tests."""
    from app.services.system_service import SystemService
    from app.simulation.fleet import Fleet

    async with state.db.sessionmaker() as session:
        uow = UnitOfWork(session, state.bus, SIMULATION_ACTOR)
        if await SystemService(uow).operation_mode() != OperationMode.SIMULATION:
            await session.rollback()
            return 0
        fleet = Fleet(uow, state.routing)
        clock = await fleet.clock()
        positions = await fleet.tick()
        for cc_id, items in positions.items():
            uow.emit(
                "vehicle.positions",
                {
                    "sim_time": round(clock.now(), 1),
                    "factor": clock.factor,
                    "paused": clock.paused,
                    "positions": items,
                },
                channels=[f"cc:{cc_id}"],
                required_permission="incidents.read",
            )
        await uow.commit()
        return sum(len(v) for v in positions.values())


class SimulationRunner:
    def __init__(self, state: Any, interval: float = 1.0) -> None:
        self.state = state
        self.interval = interval
        self._task: asyncio.Task[None] | None = None
        self._leader: AsyncConnection | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="simulation-runner")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        await self._release()

    async def _release(self) -> None:
        """Give up leadership. The lock is session-level and the connection goes back to the
        pool – so it must be unlocked explicitly (or the connection discarded)."""
        if self._leader is None:
            return
        conn, self._leader = self._leader, None
        try:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LEADER_LOCK})
            await conn.commit()
            await conn.close()
        except Exception:
            with contextlib.suppress(Exception):
                await conn.invalidate()  # connection unusable: drop it, the server frees the lock
                await conn.close()

    async def _is_leader(self) -> bool:
        if self._leader is not None:
            try:
                await self._leader.execute(text("SELECT 1"))
                return True
            except Exception:
                await self._release()
        conn = await self.state.db.engine.connect()
        got = (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LEADER_LOCK})).scalar()
        await conn.commit()
        if got:
            self._leader = conn
            logger.info("Simulationsdienst aktiv (dieser Prozess)")
            return True
        await conn.close()
        return False

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                if await self._is_leader():
                    await tick_once(self.state)
            except asyncio.CancelledError:
                raise
            except Exception:  # a failing tick must not stop the simulation
                logger.exception("Simulationstakt fehlgeschlagen")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval)
