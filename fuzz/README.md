# Fuzzing the C parsers

Every byte these four parsers read comes from a bus or a socket, so every byte is
untrusted. CI runs each harness under libFuzzer with AddressSanitizer and
UndefinedBehaviorSanitizer:

| Harness | Parser | What the fuzzer controls |
|---|---|---|
| `fuzz_can.c` | `Dbc_Decode` | start bit, length, byte order, signedness, DLC, payload |
| `fuzz_isotp.c` | `IsoTp_RxFeed` | a stream of CAN frames: PCI types, lengths, sequence numbers |
| `fuzz_doip.c` | `DoipGateway_HandleMessage` | a raw TCP message, including a lying length field |
| `fuzz_arinc429.c` | `Arinc429_AnalyzeWord` | arbitrary 32-bit words: labels, SSM, parity |

Run one locally (Linux or macOS, clang):

```bash
M=busbench/doip
clang -g -O1 -fsanitize=fuzzer,address,undefined -I$M/include fuzz/fuzz_doip.c $M/src/doip_gateway.c -o fuzz_doip
./fuzz_doip -max_total_time=60
```
