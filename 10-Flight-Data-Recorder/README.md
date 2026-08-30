# 10 Flight Data Recorder

The black box. A fixed size ring in non-volatile storage that keeps the most
recent N frames and can still be read after the power went away mid write.

This one ties the portfolio together: it logs decoded CAN signals from project 1
and ARINC 429 words from project 6.

## The frame

32 bytes, fixed:

```
  0..3   magic "FDR1"      12     source
  4..11  timestamp (us)    13     payload length
                           14..29 payload
                           30..31 CRC-16
```

## Three decisions, and why each one

**Fixed size frames.** A slot index is a multiply, and a frame that was half
written cannot shift everything after it out of alignment. Variable length
records would turn one torn write into a lost tail.

**Explicit serialisation, never a raw struct dump.** Struct padding and byte
order differ between the recorder and whatever machine reads the store
afterwards, and that second machine is the one that matters after an accident.

**A CRC per frame, not per file.** One torn frame costs one frame. A
whole-file checksum would cost the entire recording, which is the opposite of
what a recorder is for.

## What the tests actually prove

* 20 frames into a store that holds 8 keeps the newest 8, and the replay is
  still in time order even though the ring wrapped.
* Reopening resumes **after** the newest frame. Without that, a power cycle
  overwrites the most recent data first, which is exactly the data anyone wants.
* Flipping one byte costs exactly one frame. The other seven come back.
* A frame cut off half way through is skipped rather than misread, and counted,
  because a silently shorter timeline is the worst outcome for a recorder.

The discard count is returned rather than logged and forgotten, for the same
reason.

## Every append is flushed

Buffering would trade the last few seconds of the recording for throughput, and
those seconds are the entire reason the box exists.

## Run it

```
make run-10
python python/fdr_logger.py
python test/test_fdr_logger.py
```

Both implementations pin the same CRC-16/CCITT-FALSE check value (`0x29B1` for
`"123456789"`), so a store written by one is readable by the other.

## Simplifications

`fflush` reaches the OS, not the platter. Real crash survivability needs
`fsync` and hardware that honours it. The clock is injectable, which is what
makes the timeline deterministic in tests; a real unit takes it from the
aircraft time reference. No compression and no encryption.
