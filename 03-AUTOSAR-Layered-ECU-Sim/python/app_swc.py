"""Application software component: the overspeed warning.

Note what this file imports. Only ``rte``. It cannot see a CAN ID, a
register, or a driver function, so it does not care whether the speed
came from CAN, an analogue sensor, or a test harness. That is the entire
benefit of the layering, and it is why the same file could be moved to a
different ECU without editing a line.
"""

from __future__ import annotations

from rte import Rte, Signal

SPEED_LIMIT_KMH = 120
SIGNAL_TIMEOUT_MS = 100


class OverspeedMonitor:
    def __init__(self, rte: Rte) -> None:
        self.rte = rte
        self.latched = False
        rte.register_runnable(self.run, 20)

    def run(self) -> None:
        # A stale signal is not a slow signal, it is a missing one.
        # Treating the last known value as current is how a warning lamp
        # ends up reflecting a bus that died a minute ago.
        if not self.rte.is_fresh(Signal.VEHICLE_SPEED, SIGNAL_TIMEOUT_MS):
            self.rte.write(Signal.WARNING_LAMP, 1)      # fail visible, not silent
            return

        speed = self.rte.read(Signal.VEHICLE_SPEED)
        if speed > SPEED_LIMIT_KMH:
            self.latched = True
        # Braking is what clears it, so the driver has to react.
        if self.rte.read(Signal.BRAKE_PRESSED) and speed <= SPEED_LIMIT_KMH:
            self.latched = False

        self.rte.write(Signal.WARNING_LAMP, 1 if self.latched else 0)

