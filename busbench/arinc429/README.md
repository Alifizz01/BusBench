# 06 ARINC 429 Bus Analyzer

Project 1 again, on the avionics side. A 32 bit word and a label dictionary
instead of a CAN frame and a DBC.

```
  32     31 30    29        29 .. 11        10 9      8 .. 1
  parity |  SSM  | sign |     data      |   SDI   |  label  |
```

## Three things that catch people out

**The label is reversed.** It is transmitted most significant bit first while
every other field goes least significant bit first, so in a word held as a
normal integer the label byte comes out backwards. Label `0203` sits on the
wire as `0xC1`. Get this wrong and you do not get an error, you get a perfectly
plausible label belonging to a completely different parameter.

**Parity is odd, not even.** All 32 bits including the parity bit must contain
an odd number of ones. Flip any single bit and the count goes even, which is
exactly what the rule is for.

**Labels are octal.** Everyone in avionics writes them that way, so `0203` is
131, not 203. Reading the dictionary as decimal is a silent failure.

## A word can decode perfectly and still be meaningless

The SSM (sign/status matrix) says whether the source believes its own number.
Only `Normal Operation` means yes. The other three states are failure warning,
no computed data, and functional test.

That is why `analyze()` still returns a value for those words and `is_usable()`
is a separate question. Folding the two together would let a caller silently
treat a failure-warning word as a real airspeed. It is the same idea as signal
freshness in project 3.

## Run it

```
busbench test arinc429              # build + run the C and Python tests
busbench demo arinc429              # run the demo
```

Both read the same `data/capture.txt` and must produce the same values, so the
two implementations cannot drift apart without a test failing.

## Simplifications

BNR encoding only, no BCD and no discrete words. `Arinc429_BuildWord` exists so
the analyzer can be tested by round trip rather than against hand written hex;
a real analyzer only ever receives.
