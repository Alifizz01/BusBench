"""ISO 26262 style safety monitor: a windowed watchdog, a plausibility
check, and a central fault escalator.

Three independent mechanisms that share a module but nothing else. What
they have in common is the rule that a failure must produce a defined
state, never undefined behaviour.

    python -m busbench.safety.watchdog
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

FAULT_DEBOUNCE_COUNT = 3        # one glitchy reading must not limp-home a car
MAX_FAULTS = 32


class SafeState(IntEnum):
    NORMAL = 0
    DEGRADED = 1
    LIMP_HOME = 2
    SHUTDOWN = 3


class WindowedWatchdog:
    """The monitored task must kick inside [open, close] every cycle.

    Too early is a fault as well as too late. A task spinning in a tight
    loop kicks far more often than it should, and a plain timeout
    watchdog would happily call that healthy.
    """

    def __init__(self, window_open_ms: int, window_close_ms: int) -> None:
        if window_open_ms > window_close_ms:
            # An inverted window would accept nothing at all, which looks
            # like a permanently faulty task rather than a config bug.
            raise ValueError("watchdog window opens after it closes")
        self.open_ms = window_open_ms
        self.close_ms = window_close_ms
        self.cycle_start = 0

    def reset(self, now_ms: int) -> None:
        self.cycle_start = now_ms

    def kick(self, now_ms: int) -> bool:
        elapsed = now_ms - self.cycle_start
        if not self.open_ms <= elapsed <= self.close_ms:
            return False
        self.cycle_start = now_ms
        return True

    def poll(self, now_ms: int) -> bool:
        """A real windowed watchdog is hardware and expires on its own, so
        a task that stops kicking entirely still has to be caught."""
        return (now_ms - self.cycle_start) <= self.close_ms


def plausibility_check(prev_value: float, new_value: float,
                       dt_s: float, max_rate: float) -> bool:
    """Is this reading physically reachable from the previous one?"""
    # No elapsed time means there is nothing to judge, and dividing by it
    # would produce an infinity that then compares as plausible. Refuse.
    if not dt_s > 0.0 or max_rate < 0.0:
        return False
    if math.isnan(prev_value) or math.isnan(new_value):
        return False
    return abs(new_value - prev_value) / dt_s <= max_rate


@dataclass
class _Fault:
    severity: int
    count: int = 0


class FaultMonitor:
    """Every fault source reports here, so there is exactly one answer to
    the question of what state the vehicle is in."""

    def __init__(self) -> None:
        self._faults: dict[int, _Fault] = {}
        self.state = SafeState.NORMAL

    @staticmethod
    def _state_for(severity: int) -> SafeState:
        if severity >= 3:
            return SafeState.SHUTDOWN
        if severity == 2:
            return SafeState.LIMP_HOME
        if severity == 1:
            return SafeState.DEGRADED
        return SafeState.NORMAL

    def _recompute(self) -> None:
        # Recomputed from scratch each time, so healing a fault can
        # actually lower the state and two sources can never disagree.
        confirmed = [self._state_for(f.severity) for f in self._faults.values()
                     if f.count >= FAULT_DEBOUNCE_COUNT]
        self.state = max(confirmed, default=SafeState.NORMAL)

    def report(self, fault_id: int, severity: int) -> SafeState:
        fault = self._faults.get(fault_id)
        if fault is None:
            if len(self._faults) >= MAX_FAULTS:
                # Running out of room is itself unsafe, and the safe
                # answer is the most restrictive state, not "fine".
                return SafeState.SHUTDOWN
            fault = self._faults[fault_id] = _Fault(severity)
        fault.severity = severity
        fault.count = min(fault.count + 1, FAULT_DEBOUNCE_COUNT)
        self._recompute()
        return self.state

    def heal(self, fault_id: int) -> None:
        self._faults.pop(fault_id, None)
        self._recompute()


def demo() -> None:
    wd = WindowedWatchdog(8, 12)
    print("kick at 10 ms:", wd.kick(10), " kick 2 ms later:", wd.kick(12))

    print("0 to 50 km/h in 1 s :", plausibility_check(0, 50, 1.0, 100))
    print("0 to 500 km/h in 1 s:", plausibility_check(0, 500, 1.0, 100))

    fm = FaultMonitor()
    for i in range(1, 4):
        print(f"sensor fault report {i}: {fm.report(0x100, 2).name}")
    for _ in range(FAULT_DEBOUNCE_COUNT):
        fm.report(0x300, 3)
    print("plus a severity 3 fault:", fm.state.name)
    fm.heal(0x300)
    print("after healing it      :", fm.state.name)


if __name__ == "__main__":
    demo()
