# 08 ARINC 653 Partition Scheduler

How flight software of different criticality shares one CPU safely. Each
partition gets a fixed slice of a repeating major frame, and can never see
another partition's memory or take its CPU time, no matter how buggy it is.

```
  major frame = 40 ms
  |<-- FMS 10 ms -->|<- GREEDY 5 ->|<- NOSY 5 ->|<---- idle ---->|
  0                10             15           20               40
```

## The one line that is the whole guarantee

```
  now_ms = frame_start + partition.offset_ms
```

The frame advances on the clock, not on partitions finishing. A partition that
runs long is cut off at its own boundary, and the next one still starts exactly
on its offset.

The demo proves it with a partition that is an infinite loop. Over three
frames it overruns three times and every other partition still runs, still on
schedule, with a zero in its own overrun counter. That is what makes it safe to
put badly behaved software next to critical software.

## Space partitioning

Every memory access names a region, and a partition may only touch its own. An
MPU does this in hardware; here it is checked at the API boundary and logged
against whoever tried. The `NOSY` partition attempts a read and a write into
the flight management region every frame, is refused every time, and the flight
management partition reads back its own value rather than the 999 its neighbour
tried to plant.

## Bad schedules are build errors

`Configure` rejects overlapping slices and any slice that runs past the end of
the major frame. In a real ARINC 653 system the schedule is fixed offline and
cannot change at runtime, which is precisely why it is certifiable: there is no
code path that can get it wrong later.

## Run it

```
busbench test arinc653              # build + run the C and Python tests
busbench demo arinc653              # run the demo
```

## Simplifications

Preemption is cooperative. A partition spends its slice through `Part_Work()`,
which returns false once the budget is gone, rather than being interrupted by a
timer. That is a real ceiling: a partition that loops without calling `work()`
would hang this simulator, where a real RTOS would cut it off regardless. The
part that matters, that overrun time is charged to the overrunner and to nobody
else, holds either way.

No inter-partition ports (queuing or sampling), no per-partition process
scheduling inside a slice.
