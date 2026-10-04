"""Integration layer: the only place allowed to see every layer at once.

In a real project this is the ECU configuration, generated from ARXML.
It wires BSW to RTE to application and then gets out of the way. Note
that no layer imports another sideways, they only meet here.

    python -m busbench.autosar.ecu
"""

from __future__ import annotations

from .bsw import Bsw
from .rte import Rte, Signal
from .swc import OverspeedMonitor


def build_ecu() -> tuple[Rte, Bsw, OverspeedMonitor]:
    """The ECU configuration: one RTE, the BSW, the application."""
    rte = Rte()
    bsw = Bsw(rte)                        # BSW first, so its data is published first
    return rte, bsw, OverspeedMonitor(rte)


def main() -> None:
    rte, bsw, _ = build_ecu()
    bsw.traffic_enabled = True

    print("  t(ms)   speed   rpm  brake  lamp")
    for _ in range(6):
        rte.start(200)
        print(f"  {rte.now_ms:5d}  {rte.read(Signal.VEHICLE_SPEED):6d}"
              f"  {rte.read(Signal.ENGINE_RPM):4d}"
              f"  {rte.read(Signal.BRAKE_PRESSED):5d}  {int(bsw.lamp_on):4d}")


if __name__ == "__main__":
    main()
