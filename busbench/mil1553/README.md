# 07 MIL-STD-1553 Bus Controller

The opposite philosophy to ARINC 429. There, every source shouts and nobody
coordinates. Here one Bus Controller polls up to 31 Remote Terminals on a fixed
schedule, no RT ever speaks first, and there is no arbitration at all. That is
exactly why it is used where timing has to be provable rather than measured.

```
  Command word, 16 bits
  15 .. 11    10     9 .. 5        4 .. 0
  RT address  T/R    subaddress    word count or mode code
```

## Two encoding traps in five bits

**Word count 32 goes on the wire as 0.** Five bits have to cover a count that
runs 1 to 32, so 32 borrows the unused zero.

**Unless the subaddress is 0 or 31.** Then those same five bits are a mode code,
not a count, and code 0 is a real mode code that must not be turned into 32.
Both directions are tested.

## Failure is a first class case

A 1553 bus has no negative acknowledge. An RT either answers or it does not, so
the BC has to distinguish four different kinds of not-quite-working:

| Situation | What the BC sees |
| --- | --- |
| No RT at that address | Silence, which is a timeout |
| RT busy | A status word with the busy bit, and no data |
| Fewer words than asked for | Message error |
| Subsystem flag set | The transfer worked, the data is not trustworthy |

That last one is the dangerous one. The words arrive intact, so it is tempting
to use them. Handing them on without the flag is how bad data reaches a flight
control law.

**Broadcast (address 31) gets no status word at all.** Every RT takes the data
and none of them answers. A BC that waits for a status word after a broadcast
times out every single time, on a bus that is working perfectly.

## The schedule keeps running

`run_schedule` retries a failed slot exactly once and then moves on. A BC that
blocks on one sulking terminal misses the deadline of every other RT on the
bus, and those deadlines do not care why. The stats counters exist so a
silently degraded bus still shows up as a number.

## Run it

```
busbench test mil1553              # build + run the C and Python tests
busbench demo mil1553              # run the demo
```

## C and Python differ on purpose

The C transaction returns `false` and fills a status word. The Python one
raises, so a caller cannot read the data buffer after a failure by forgetting
to check a return value.

## Simplifications

No word level encoding (sync pattern, Manchester, per-word parity) and no dual
redundant bus A/B switching. Time in the schedule is ordering only, not a real
clock, which is what makes the frame test deterministic.
