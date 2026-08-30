"""Protocol tests with no sockets, then one real TCP round trip.

Splitting them is the point of the design: the awkward cases are plain
buffers, and only the framing needs a network to prove.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import doip                                            # noqa: E402
from doip import DoipClient, Gateway, build, tiny_ecu  # noqa: E402


def type_of(frame: bytes) -> int:
    return doip.parse_header(frame)[0]


def test_header_round_trip():
    frame = build(doip.DIAG_MESSAGE, b"\x01\x02\x03")
    assert len(frame) == doip.HEADER_LEN + 3
    assert doip.parse_header(frame) == (doip.DIAG_MESSAGE, 3)


def test_bad_version_pattern_is_rejected():
    """Byte 1 must be the complement of byte 0. Corrupt it and nothing in
    the message gets believed."""
    frame = bytearray(build(doip.DIAG_MESSAGE, b"\x01\x02\x03"))
    frame[1] = 0x00
    reply = Gateway(tiny_ecu).handle(bytes(frame))
    assert type_of(reply) == doip.GENERIC_NACK
    assert reply[doip.HEADER_LEN] == doip.NACK_INCORRECT_PATTERN


def test_lying_length_field_is_rejected():
    """The classic buffer overrun: a header claiming more than arrived."""
    frame = bytearray(build(doip.DIAG_MESSAGE, b"\x01\x02\x03"))
    frame[7] = 200                              # claim 200 bytes, send 3
    reply = Gateway(tiny_ecu).handle(bytes(frame))
    assert reply[doip.HEADER_LEN] == doip.NACK_INVALID_LENGTH


def test_identification_works_before_activation():
    reply = Gateway(tiny_ecu).handle(build(doip.VEHICLE_IDENT_REQ))
    assert type_of(reply) == doip.VEHICLE_IDENT_RESP
    assert reply[doip.HEADER_LEN:doip.HEADER_LEN + 17] == doip.VIN


def test_diagnostics_before_activation_are_refused():
    """The check the whole state machine exists for."""
    gw = Gateway(tiny_ecu)
    diag = build(doip.DIAG_MESSAGE, b"\x0e\x00\x00\x10\x22\xf1\x90")
    assert type_of(gw.handle(diag)) == doip.DIAG_NACK
    assert not gw.routing_active


def test_address_zero_cannot_activate():
    gw = Gateway(tiny_ecu)
    reply = gw.handle(build(doip.ROUTING_ACTIVATION_REQ, b"\x00\x00\x00" + bytes(4)))
    assert reply[doip.HEADER_LEN + 4] == doip.ROUTING_UNKNOWN_SOURCE
    assert not gw.routing_active


def test_second_tester_cannot_ride_the_first_activation():
    gw = Gateway(tiny_ecu)
    gw.handle(build(doip.ROUTING_ACTIVATION_REQ, b"\x0e\x00\x00" + bytes(4)))
    assert gw.routing_active

    ours = build(doip.DIAG_MESSAGE, b"\x0e\x00\x00\x10\x22\xf1\x90")
    assert type_of(gw.handle(ours)) == doip.DIAG_MESSAGE

    theirs = build(doip.DIAG_MESSAGE, b"\x0e\x01\x00\x10\x22\xf1\x90")
    assert type_of(gw.handle(theirs)) == doip.DIAG_NACK


def test_unknown_payload_type_gets_an_answer():
    """Silence is not a protocol response."""
    reply = Gateway(tiny_ecu).handle(build(0x1234))
    assert reply[doip.HEADER_LEN] == doip.NACK_UNKNOWN_PAYLOAD


def test_real_tcp_round_trip():
    port = doip.start_background(Gateway(tiny_ecu))
    with DoipClient(port=port) as tester:
        assert tester.identify()[:17] == doip.VIN

        try:
            tester.send_uds(b"\x22\xf1\x90")
        except PermissionError:
            pass
        else:
            raise AssertionError("UDS before routing activation must be refused")

        assert tester.activate_routing() == doip.ROUTING_SUCCESS
        assert tester.send_uds(b"\x22\xf1\x90") == b"\x62\xf1\x90" + doip.VIN


def test_a_message_split_across_two_packets_still_arrives():
    """TCP may deliver half a header. The gateway has to wait for the rest
    instead of deciding the message is malformed."""
    port = doip.start_background(Gateway(tiny_ecu))
    with DoipClient(port=port) as tester:
        frame = build(doip.ROUTING_ACTIVATION_REQ, b"\x0e\x00\x00" + bytes(4))
        tester.sock.sendall(frame[:5])          # mid header
        time.sleep(0.05)
        tester.sock.sendall(frame[5:])
        reply = doip.recv_message(tester.sock)
        assert reply[doip.HEADER_LEN + 4] == doip.ROUTING_SUCCESS


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all assertions passed")
