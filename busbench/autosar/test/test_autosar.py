"""Behaviour tests for the layered stack, plus one test that checks the
architecture itself rather than the behaviour."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from busbench.autosar.swc import OverspeedMonitor
from busbench.autosar.bsw import Bsw
from busbench.autosar.rte import Rte, Signal


def build():
    rte = Rte()
    bsw = Bsw(rte)                        # BSW first, so its data lands first
    OverspeedMonitor(rte)
    return rte, bsw


# @req REQ-301
def test_freshness():
    rte = Rte()
    assert not rte.is_fresh(Signal.VEHICLE_SPEED, 100)      # never written
    rte.write(Signal.VEHICLE_SPEED, 50)
    assert rte.read(Signal.VEHICLE_SPEED) == 50
    assert rte.is_fresh(Signal.VEHICLE_SPEED, 100)
    rte.start(500)
    assert not rte.is_fresh(Signal.VEHICLE_SPEED, 100)


# @req REQ-302
def test_overspeed_latches_until_braking():
    rte, bsw = build()

    bsw.inject_can_frame(0x101, (10000).to_bytes(2, "big") + b"\x00")   # 100 km/h
    rte.start(60)
    assert rte.read(Signal.VEHICLE_SPEED) == 100
    assert not bsw.lamp_on

    bsw.inject_can_frame(0x101, (14000).to_bytes(2, "big") + b"\x00")   # 140 km/h
    rte.start(60)
    assert bsw.lamp_on

    # Slowing down alone does not clear it, the driver has to brake.
    bsw.inject_can_frame(0x101, (8000).to_bytes(2, "big") + b"\x00")    # 80 km/h
    rte.start(60)
    assert bsw.lamp_on

    bsw.inject_can_frame(0x101, (8000).to_bytes(2, "big") + b"\x01")    # braking
    rte.start(60)
    assert not bsw.lamp_on


# @req REQ-303
def test_dead_bus_lights_the_lamp():
    """The last good value must never be mistaken for a current one."""
    rte, bsw = build()
    bsw.inject_can_frame(0x101, (8000).to_bytes(2, "big") + b"\x01")
    rte.start(60)
    assert not bsw.lamp_on

    rte.start(500)                        # nothing arrives for half a second
    assert not rte.is_fresh(Signal.VEHICLE_SPEED, 100)
    assert bsw.lamp_on


# @req REQ-304
def test_application_never_reaches_into_the_driver():
    """The architecture rule, enforced instead of just documented.

    If someone adds a driver include to the application to save five
    minutes, this fails. That is the whole reason AUTOSAR has an RTE.
    """
    forbidden = ("bsw", "can_driver", "adc", "port", "dio")

    py = (ROOT / "swc.py").read_text()
    for module in re.findall(r"^\s*(?:from|import)\s+\.*(\w+)", py, re.M):
        assert module not in forbidden, f"swc.py imports {module}"

    c = (ROOT / "src" / "app_swc.c").read_text()
    for header in re.findall(r'#include\s+"([^"]+)"', c):
        assert header == "rte.h", f"app_swc.c includes {header}, only rte.h is allowed"


if __name__ == "__main__":
    test_freshness()
    test_overspeed_latches_until_braking()
    test_dead_bus_lights_the_lamp()
    test_application_never_reaches_into_the_driver()
    print("all assertions passed")
