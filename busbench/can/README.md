# 01 CAN Bus Sniffer and DBC Decoder

Reads raw CAN traffic and turns it into named signals with units, using a DBC
file as the dictionary. This is the first tool you need on any vehicle project:
before you can write an ECU, you have to be able to see what is on the bus.

## The interesting part

A DBC signal says where its bits live, and there are two incompatible ways to
lay them out:

* **Intel (`@1`)** counts upward from the start bit, least significant bit first.
* **Motorola (`@0`)** treats the start bit as the *most* significant bit, walks
  downward inside the byte, then jumps to the top bit of the next byte.

Get this backwards and every value looks plausible but is wrong, which is why
both cases plus a signed Motorola signal are pinned down in the tests.

Physical value is `raw * scale + offset`, and a signal declared `-` is two's
complement, so it needs sign extension before scaling.

## Run it

```
busbench test can              # build + run the C and Python tests
busbench demo can              # run the demo
```

Both print the same decoded bus. `data/example.log` is in the format
`candump -l` writes, so no CAN hardware is involved.

## Files

| Path | What |
| --- | --- |
| `include/can_sniffer.h` | Interface, the contract both versions follow |
| `src/can_sniffer.c` | C implementation |
| `decoder.py` | Python implementation and CLI |
| `test/` | Assertion tests for both, same expected values |
| `data/` | Example DBC and candump log |

## Simplifications

Parses the `BO_` and `SG_` lines of a DBC, which is what a decoder needs.
Value tables, multiplexed signals, and extended (29 bit) IDs are not handled.
