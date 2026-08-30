"""Basic Software: the simulated CAN driver and the lamp output driver.

It talks to hardware on one side and to the RTE on the other, and it
never calls the application. Data flows up through ``rte.write``,
commands flow down through ``rte.read``.
"""

from __future__ import annotations

from rte import Rte, Signal

CAN_ID_ENGINE = 0x100
CAN_ID_CHASSIS = 0x101


class Bsw:
    def __init__(self, rte: Rte) -> None:
        self.rte = rte
        self.engine = bytearray(8)
        self.chassis = bytearray(8)
        self.lamp_on = False
        self.traffic_enabled = False
        self._tick = 0
        rte.register_runnable(self.main_function, 10)

    def _publish_engine(self) -> None:
        # Same bit layout as project 1: raw counts, scaled here so the
        # application only ever sees engineering units.
        self.rte.write(Signal.ENGINE_RPM, int.from_bytes(self.engine[0:2], "little") // 4)

    def _publish_chassis(self) -> None:
        self.rte.write(Signal.VEHICLE_SPEED, int.from_bytes(self.chassis[0:2], "big") // 100)
        self.rte.write(Signal.BRAKE_PRESSED, self.chassis[2] & 0x01)

    def main_function(self) -> None:
        """Scheduled by the RTE like any other runnable. In real AUTOSAR
        the BSW Scheduler does this, but the shape is the same."""
        if self.traffic_enabled:
            self._tick += 1
            rpm_raw = 3200 + (self._tick % 40) * 100          # 800 to 1800 rpm
            self.engine[0:2] = rpm_raw.to_bytes(2, "little")
            speed_raw = (self._tick % 200) * 100              # 0 to 199 km/h
            self.chassis[0:2] = speed_raw.to_bytes(2, "big")
            self.chassis[2] = 1 if (self._tick % 50) < 5 else 0
            self._publish_engine()
            self._publish_chassis()

        # Output direction: whatever the application decided last tick.
        self.lamp_on = self.rte.read(Signal.WARNING_LAMP) != 0

    def inject_can_frame(self, can_id: int, data: bytes) -> None:
        if can_id == CAN_ID_ENGINE:
            self.engine[:len(data)] = data
            self._publish_engine()
        elif can_id == CAN_ID_CHASSIS:
            self.chassis[:len(data)] = data
            self._publish_chassis()
