# 05 DoIP Gateway (CAN to Ethernet)

ISO 13400: UDS diagnostics carried over TCP instead of CAN, which is how a
modern car lets a garage plug in an Ethernet cable instead of an OBD dongle.

Every message starts with the same 8 bytes:

```
  version | inverse version | payload type (2) | payload length (4)
```

## The design decision

The protocol state machine is in one file and the sockets are in another.

That split is why the awkward cases are testable at all. A bad version byte, a
length field that claims 200 bytes when 3 arrived, a diagnostic request sent
before routing activation: all of these are a buffer in and a buffer out, with
no network anywhere near them. Only the framing itself needs a real socket to
prove, and there is one test for that.

## Three things a gateway must get right

* **The inverse version byte.** Byte 1 has to be the complement of byte 0.
  It costs nothing and it catches a stream that is not DoIP before anything
  in it is believed.
* **A length field is a claim, not a fact.** It is checked against how many
  bytes actually arrived. Trusting it is the classic way to walk a parser off
  the end of its buffer.
* **Routing activation gates everything.** Without that check, anyone who can
  reach port 13400 can send UDS to the car. The tests confirm that diagnostics
  before activation are refused, that source address `0x0000` cannot activate,
  and that a second tester cannot ride the first one's session.

The gateway understands none of the UDS it carries. It forwards to a handler,
so adding a diagnostic service never means editing gateway code.

## TCP is a stream, not a message queue

One `recv` can return half a message or three of them stuck together. Both
implementations buffer until a whole message is present. There is a test that
sends a message split across two packets, mid header, to prove it.

## Run it

```
busbench test doip              # build + run the C and Python tests
busbench demo doip              # run the demo
```

The two implementations speak the same wire, so they interoperate: `busbench test doip`
builds the C gateway, starts it on 127.0.0.1:13400 and drives it with the Python tester
(identify, refused diagnostics before activation, routing activation, VIN over TCP).
In Studio, pick **C gateway** on the DoIP page to do the same by hand.

The Python gateway can also route diagnostics to the simulated ECU from the
[UDS module](../uds) over ISO-TP, the gateway's real job:

```python
from busbench.doip import DoipClient, Gateway, start_background, uds_ecu_handler
port = start_background(Gateway(uds_ecu_handler()))
with DoipClient(port=port) as tester:
    tester.activate_routing()
    print(tester.send_uds(b"\x22\xf1\x90"))     # VIN, segmented onto the CAN side
```

## Simplifications

Loopback only and one tester at a time, so there is no TLS, no UDP vehicle
discovery, no alive check, and no concurrent connection handling. The CAN side
is a handler function rather than a real ISO-TP stack; project 2 is where that
lives.
