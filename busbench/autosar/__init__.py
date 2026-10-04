"""AUTOSAR classic layering: BSW -> RTE -> application SWC, wired by an ECU config."""
from .bsw import Bsw
from .ecu import build_ecu
from .rte import Rte, Signal
from .swc import OverspeedMonitor
