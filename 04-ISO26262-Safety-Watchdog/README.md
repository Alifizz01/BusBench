# 04 ISO 26262 Safety Watchdog

Three mechanisms that turn "the software misbehaved" into a defined vehicle
state instead of undefined behaviour.

## Windowed watchdog

The monitored task must kick inside `[open, close]` every cycle. **Too early is
a fault as well as too late.** A plain timeout watchdog only catches a task that
hung. A task stuck in a tight loop kicks far more often than it should, and a
timeout watchdog calls that perfectly healthy. The window catches both.

`Watchdog_Poll()` exists because a real windowed watchdog is hardware and
expires on its own, so a task that stops kicking entirely still has to be
caught by something.

## Plausibility check

Rate of change against physics: 0 to 100 km/h in 100 ms is not a car, it is a
broken sensor. Note that `dt = 0` returns false rather than dividing by zero,
because an infinite rate would otherwise compare as plausible.

## Central fault escalation

Every fault source reports to one place, so there is exactly one answer to the
question of what state the vehicle is in.

* **Debounce.** A fault counts only after `FAULT_DEBOUNCE_COUNT` reports. One
  noisy reading must not put a car into limp home.
* **Worst wins.** The state is recomputed from all confirmed faults, so a mild
  fault reported later cannot talk the state back down.
* **Healing steps down.** Clearing the worst fault drops to the next worst, not
  straight to normal.
* **Overflow is unsafe.** Running out of fault slots returns `SHUTDOWN`, not a
  quiet "everything is fine".

## Run it

```
make run-04
python python/watchdog.py
python test/test_watchdog.py
```

## Simplifications

Time is passed in as a parameter rather than read from a clock, which is what
makes every case above testable. Severity maps to state with a fixed table; a
real project derives it from an ASIL hazard analysis.
