import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from watchdog import (FAULT_DEBOUNCE_COUNT, FaultMonitor, SafeState,      # noqa: E402
                      WindowedWatchdog, plausibility_check)


def test_window_rejects_early_and_late():
    wd = WindowedWatchdog(8, 12)          # a healthy 10 ms task
    assert wd.kick(10)
    assert wd.kick(20)
    assert not wd.kick(22)                # 2 ms later, far too early
    wd.reset(22)
    assert not wd.kick(40)                # 18 ms later, too late


def test_silent_task_is_caught():
    wd = WindowedWatchdog(8, 12)
    wd.reset(100)
    assert wd.poll(110)
    assert not wd.poll(120)


def test_inverted_window_is_a_config_error():
    try:
        WindowedWatchdog(20, 10)
    except ValueError:
        return
    raise AssertionError("an inverted window must be rejected")


def test_plausibility():
    assert plausibility_check(0.0, 5.0, 0.1, 100.0)          # 50 km/h per s
    assert not plausibility_check(0.0, 100.0, 0.1, 100.0)    # 1000 km/h per s
    assert plausibility_check(80.0, 75.0, 0.1, 100.0)        # braking is fine
    assert not plausibility_check(0.0, 1.0, 0.0, 100.0)      # no time, no verdict
    assert not plausibility_check(float("nan"), 1.0, 0.1, 100.0)


def test_faults_debounce_escalate_and_heal():
    fm = FaultMonitor()

    # One report is a glitch, not a fault.
    assert fm.report(0x100, 2) == SafeState.NORMAL
    assert fm.report(0x100, 2) == SafeState.NORMAL
    assert fm.report(0x100, 2) == SafeState.LIMP_HOME

    # A milder fault must not talk the state back down.
    for _ in range(FAULT_DEBOUNCE_COUNT):
        fm.report(0x200, 1)
    assert fm.state == SafeState.LIMP_HOME

    # A worse one escalates as soon as it is confirmed.
    for _ in range(FAULT_DEBOUNCE_COUNT):
        fm.report(0x300, 3)
    assert fm.state == SafeState.SHUTDOWN

    # Healing steps back down one level at a time, never straight to normal.
    fm.heal(0x300)
    assert fm.state == SafeState.LIMP_HOME
    fm.heal(0x100)
    assert fm.state == SafeState.DEGRADED
    fm.heal(0x200)
    assert fm.state == SafeState.NORMAL


def test_fault_table_overflow_is_not_normal():
    fm = FaultMonitor()
    for i in range(40):
        state = fm.report(0x1000 + i, 1)
        if i >= 32:
            assert state == SafeState.SHUTDOWN


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all assertions passed")
