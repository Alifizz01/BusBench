"""ISO 26262 safety mechanisms: windowed watchdog, plausibility check, fault escalation."""
from .watchdog import FaultMonitor, SafeState, WindowedWatchdog, plausibility_check
