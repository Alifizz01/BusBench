# 02 UDS Diagnostic Client

The scan-tool side of ISO 14229, running over ISO-TP segmented CAN. A
simulated ECU is included so the whole session runs with no hardware.

## The two layers

**ISO-TP (ISO 15765-2)** carries a message longer than 8 bytes over CAN:

| Frame | First byte | Meaning |
| --- | --- | --- |
| Single | `0x0L` | whole payload fits in one frame |
| First | `0x1L LL` | start of a long message, 12 bit length |
| Flow control | `0x30 BS STmin` | receiver grants permission to continue |
| Consecutive | `0x2N` | N is a wrapping 1 to 15 counter |

That counter is the point of the protocol. A dropped frame shows up as a
sequence gap, so the receiver can fail instead of quietly returning a message
with a hole in it. There is a test for exactly that.

**UDS** on top: session control (`0x10`), read by identifier (`0x22`), security
access (`0x27`), write by identifier (`0x2E`).

## The two things that bite people

* **`0x78` responsePending is not an error.** A slow ECU sends it repeatedly
  while it works. A client that treats it as a failure looks broken against
  perfectly healthy hardware. This client loops on it.
* **Security is a two-step handshake.** Request a seed, transform it into a
  key, send the key at `level + 1`. The transform here stands in for the
  manufacturer's algorithm, which normally lives in an HSM.

The simulated ECU refuses things the way a real one does: wrong session,
still locked, unknown identifier. The tests check the refusals as carefully
as the successes.

## Run it

```
make run-02
python python/uds_client.py
python test/test_uds_client.py
```

## C and Python differ on purpose

The C client returns `UdsResult_t` and stores the negative response code for
`Uds_GetLastNrc()`. The Python client raises `NegativeResponse` instead, so a
caller cannot ignore a refusal by forgetting to check a return value. Same
protocol, each language done its own way.

## Simplifications

Timing is poll-count based rather than a real P2 / P2* clock, because the
simulated bus is synchronous. Flow control is always sent with block size 0
and STmin 0, so the block-size pause path is not exercised.
