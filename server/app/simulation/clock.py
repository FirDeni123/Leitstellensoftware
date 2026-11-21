"""Simulation clock: simulated seconds, with pause and time factor (Zeitraffer).

``sim_now = base_sim + (real_now − base_real) × factor`` while running, frozen while paused.
All movement times are stored in simulation seconds, so pausing or speeding up the clock
moves every vehicle consistently, and positions can be reconstructed after a restart.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace

from app.models import SystemSetting
from app.services.uow import UnitOfWork

CLOCK_KEY = "simulation_clock"
FACTORS = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0)


def real_time() -> float:  # tests replace this
    return time.time()


@dataclass(frozen=True, slots=True)
class ClockState:
    base_real: float
    base_sim: float
    factor: float = 1.0
    paused: bool = False

    def now(self, real: float | None = None) -> float:
        if self.paused:
            return self.base_sim
        return self.base_sim + ((real_time() if real is None else real) - self.base_real) * self.factor

    def rebased(self, *, factor: float | None = None, paused: bool | None = None) -> ClockState:
        real = real_time()
        return replace(
            self,
            base_real=real,
            base_sim=self.now(real),
            factor=self.factor if factor is None else factor,
            paused=self.paused if paused is None else paused,
        )


async def load_clock(uow: UnitOfWork) -> ClockState:
    row = await uow.session.get(SystemSetting, CLOCK_KEY)
    if row is None:
        now = real_time()
        return ClockState(base_real=now, base_sim=now)
    return ClockState(**row.value)


async def save_clock(uow: UnitOfWork, state: ClockState) -> SystemSetting:
    row = await uow.session.get(SystemSetting, CLOCK_KEY)
    if row is None:
        row = SystemSetting(key=CLOCK_KEY, value=asdict(state))
        uow.session.add(row)
    else:
        row.value = asdict(state)
    row.updated_by = uow.actor.user_id
    await uow.session.flush()
    return row
