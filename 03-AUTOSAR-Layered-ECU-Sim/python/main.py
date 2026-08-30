"""Integration layer: the only place allowed to see every layer at once.

In a real project this is the ECU configuration, generated from ARXML.
It wires BSW to RTE to application and then gets out of the way. Note
that no layer imports another sideways, they only meet here.

    python python/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_swc import OverspeedMonitor      # noqa: E402
from bsw import Bsw                       # noqa: E402
from rte import Rte, Signal               # noqa: E402


def main() -> None:
    rte = Rte()
    bsw = Bsw(rte)                        # BSW first, so its data is published first
    OverspeedMonitor(rte)
    bsw.traffic_enabled = True

    print("  t(ms)   speed   rpm  brake  lamp")
    for _ in range(6):
        rte.start(200)
        print(f"  {rte.now_ms:5d}  {rte.read(Signal.VEHICLE_SPEED):6d}"
              f"  {rte.read(Signal.ENGINE_RPM):4d}"
              f"  {rte.read(Signal.BRAKE_PRESSED):5d}  {int(bsw.lamp_on):4d}")


if __name__ == "__main__":
    main()
