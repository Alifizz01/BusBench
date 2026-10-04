# 03 AUTOSAR Layered ECU Simulator

The classic three layer stack, running on a PC. No ECU required.

```
  Application   app_swc      overspeed warning, sees only signals
       |
      RTE       rte          signal table + periodic scheduler
       |
      BSW       bsw          CAN driver, lamp driver, scaling
```

## The rule the whole thing exists for

The application may include `rte.h` and nothing else. It cannot see a CAN ID,
a register, or a driver function, so the same file would move to a different
ECU unedited.

That rule is usually written in a document and then quietly broken. Here it is
a test: `test_application_never_reaches_into_the_driver` scans `app_swc.c` and
`app_swc.py` and fails if either one reaches sideways. Layering that is not
enforced is just a diagram.

The one place allowed to see everything is the integration layer
(`ecu.py`), the equivalent of the generated ECU configuration.

## Signal freshness

`Rte_IsFresh(sig, max_age_ms)` exists because a signal that stopped updating is
a fault, not a valid old value. If the bus goes quiet, the application sees
stale data and lights the lamp rather than reporting a speed from a minute ago.
The simulated clock deliberately keeps running across calls to `Rte_Start`, so
this failure can actually be reproduced.

## Run it

```
busbench test autosar              # build + run the C and Python tests
busbench demo autosar              # run the demo
```

## Simplifications

Cooperative scheduling, no preemption and no priorities: a runnable that never
returns hangs the whole simulation. Project 8 is where forced preemption gets
built. Sender/receiver signals only, no client/server ports and no ARXML.
