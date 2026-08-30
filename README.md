# Automotive and Avionics Communication Portfolio

Ten small projects covering the buses and standards that vehicles and aircraft
actually run on. Every one is implemented **twice**, in C against a shared
header and in Python, and both halves are tested.

Nothing needs hardware. Every bus is simulated, so the whole portfolio builds
and runs from a clean checkout in one command.

## Run everything

```
python run_all.py
```

```
project                          C      Python
----------------------------------------------
01-CAN-Bus-Sniffer-Decoder       pass   pass
02-UDS-Diagnostic-Client         pass   pass
03-AUTOSAR-Layered-ECU-Sim       pass   pass
04-ISO26262-Safety-Watchdog      pass   pass
05-DoIP-CAN-to-Ethernet-Gateway  pass   pass
06-ARINC429-Bus-Analyzer         pass   pass
07-MIL1553-Bus-Controller-Sim    pass   pass
08-ARINC653-Partition-Scheduler  pass   pass
09-DO178C-Traceability-Tool      pass   pass
10-Flight-Data-Recorder          pass   pass
----------------------------------------------
10 projects, 0 with failures
```

`run_all.py` needs nothing but Python 3.10 or newer, and finds a compiler on
its own (including an MSYS2 one that is not on PATH). If there is no compiler
it runs the Python half and says so rather than quietly passing.

There is also a `Makefile` for `make test`, `make run-05` and so on. Run it
from a POSIX shell: MSYS2, WSL, Linux or macOS.

## The projects

| | Project | The one thing worth reading it for |
| --- | --- | --- |
| 01 | CAN sniffer and DBC decoder | Intel and Motorola bit layouts walk the message in opposite directions |
| 02 | UDS diagnostic client | `0x78` responsePending is not an error, and the ISO-TP sequence number is how a dropped frame gets caught |
| 03 | AUTOSAR layered ECU | The layering rule is enforced by a test that reads the source, not just documented |
| 04 | ISO 26262 safety watchdog | A windowed watchdog treats too early as a fault as well as too late |
| 05 | DoIP gateway | The protocol state machine is kept off the sockets, so every awkward case is a plain buffer |
| 06 | ARINC 429 analyzer | The label is bit reversed on the wire, and a word can decode perfectly and still be meaningless |
| 07 | MIL-STD-1553 bus controller | Word count 32 encodes as 0, unless the subaddress makes those bits a mode code |
| 08 | ARINC 653 partition scheduler | The frame advances on the clock, so a hung partition can only ever hurt itself |
| 09 | DO-178C traceability tool | Reads the source back, because a requirement whose test was deleted still looks traced |
| 10 | Flight data recorder | A CRC per frame, not per file, so one torn write costs one frame |

Each project has its own README explaining what it does, the design decision
behind it, and what has deliberately been left out.

## Layout

Every project has the same shape:

```
NN-Project-Name/
  include/    the C header, which is the interface contract both versions follow
  src/        C implementation
  python/     Python implementation, runnable as a CLI or demo
  test/       test_x.c and test_x.py, assertion based, no test framework
  data/       sample logs, dictionaries and captures where a project needs them
  README.md
```

The C tests print a short trace as they run, so each one doubles as the demo.

## Why both languages

They are not translations of each other. Each half is written the way that
language is actually written, and the differences are called out in the
project READMEs. The clearest example is error reporting: the C clients return
a result code you have to check, while the Python ones raise, so a caller
cannot use a buffer after a failure by forgetting to look at a return value.

Where both halves share a file format, they pin the same expected values. The
ARINC 429 capture, the CRC check value in project 10 and the traceability
verdict in project 09 are all asserted on both sides, so the two
implementations cannot drift apart without a test going red.

Project 05 goes further: the Python tester talks to the C gateway over real
TCP on port 13400.

## Notes

* Written against C11 and Python 3.10, standard library only, no third party
  packages and no build system beyond `make` or the Python runner.
* Some headers gained declarations the original stubs did not have. Each
  addition is marked `added:` in the header with the reason, and the original
  declarations are untouched.
* Every project README ends with a **Simplifications** section listing what was
  deliberately left out. They are choices, not oversights.
