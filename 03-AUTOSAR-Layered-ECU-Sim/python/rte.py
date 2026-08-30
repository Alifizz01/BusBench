"""The Runtime Environment: a signal table and a periodic scheduler.

Deliberately small. Its value is not what it does but what it stops
anyone from doing, which is calling across layers directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum


class Signal(IntEnum):
    VEHICLE_SPEED = 0
    ENGINE_RPM = 1
    BRAKE_PRESSED = 2
    WARNING_LAMP = 3        # an output, so the application has something to drive


@dataclass
class _Slot:
    value: int = 0
    last_write_ms: int = 0
    ever_written: bool = False


class Rte:
    def __init__(self) -> None:
        self._signals = {sig: _Slot() for sig in Signal}
        self._tasks: list[tuple[Callable[[], None], int]] = []
        self.now_ms = 0

    def read(self, sig: Signal) -> int:
        return self._signals[sig].value

    def write(self, sig: Signal, value: int) -> None:
        slot = self._signals[sig]
        slot.value = value
        slot.last_write_ms = self.now_ms
        slot.ever_written = True

    def is_fresh(self, sig: Signal, max_age_ms: int) -> bool:
        """A signal that stopped updating is a fault, not a valid old value."""
        slot = self._signals[sig]
        return slot.ever_written and (self.now_ms - slot.last_write_ms) <= max_age_ms

    def register_runnable(self, fn: Callable[[], None], period_ms: int) -> None:
        if period_ms <= 0:
            raise ValueError("a runnable needs a positive period")
        self._tasks.append((fn, period_ms))

    def start(self, duration_ms: int, tick_ms: int = 10) -> None:
        """Runs for duration_ms more of simulated time.

        Time carries on across calls. Restarting the clock at zero would
        make every signal look freshly written, which is exactly the bug
        the freshness check exists to catch.
        """
        end = self.now_ms + duration_ms
        while self.now_ms < end:
            self.now_ms += tick_ms
            # Registration order is execution order within a tick, which
            # is why BSW registers first: its data is already published
            # when the application runnables read it in the same tick.
            for fn, period in self._tasks:
                if self.now_ms % period == 0:
                    fn()
