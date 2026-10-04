"""Walks the full diagnostic session the way a scan tool does, and checks
the refusals as carefully as the successes. An ECU that says yes to
everything is the bug."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from busbench.uds import isotp
from busbench.uds.ecu import EcuSim, key_from_seed
from busbench.uds.client import NegativeResponse, UdsClient


def refused(fn, *args) -> int:
    """Runs fn, asserts it was refused, returns the NRC."""
    try:
        fn(*args)
    except NegativeResponse as exc:
        return exc.nrc
    raise AssertionError(f"{fn.__name__} should have been refused")


# @req REQ-201
def test_session():
    ecu = EcuSim()
    c = UdsClient(ecu.client_send, ecu.client_recv)

    c.start_session(0x01)

    # 20 byte response, so ISO-TP has to segment and reassemble it.
    assert c.read_data_by_identifier(0xF190) == b"WVWZZZ1JZ3W386752"
    assert c.read_data_by_identifier(0xF195) == b"1.4.2"

    # This one answers 0x78 first, the client must keep waiting.
    assert c.read_data_by_identifier(0x0110) == b"\x0f\xa0"

    # An identifier the ECU does not have is a refusal, not a timeout.
    assert refused(c.read_data_by_identifier, 0xDEAD) == 0x31

    # Security is not even offered in the default session.
    assert refused(c.request_seed, 0x01) == 0x7F

    c.start_session(0x03)

    # Writing is refused while locked. This is the check that matters.
    assert refused(c.write_data_by_identifier, 0xF199, b"\x12\x34") == 0x33

    # A wrong key must not unlock anything.
    c.request_seed(0x01)
    assert refused(c.security_access, 0x02, b"\x00\x00\x00\x00") == 0x35
    assert not ecu.unlocked

    seed = c.unlock()
    assert ecu.unlocked
    assert key_from_seed(seed) == key_from_seed(ecu.seed)

    c.write_data_by_identifier(0xF199, b"\x12\x34")
    assert ecu.written[0xF199] == b"\x12\x34"

    # Dropping back to the default session relocks it.
    c.start_session(0x01)
    assert not ecu.unlocked
    assert refused(c.write_data_by_identifier, 0xF199, b"\x12\x34") == 0x33

    # A long request has to segment outbound too, not just inbound.
    c.start_session(0x03)
    assert refused(c.write_data_by_identifier, 0xF199, bytes(40)) == 0x33


# @req REQ-202
def test_isotp_catches_a_dropped_frame():
    """The sequence number is the whole reason ISO-TP has one: a message
    with a gap must fail, not come back quietly corrupted."""
    rx = isotp.IsoTpRx()
    sent = []

    assert rx.feed(bytes([0x10, 0x14]) + b"ABCDEF", sent.append) is None
    assert sent == [bytes([0x30, 0x00, 0x00])]          # flow control went out
    assert rx.feed(bytes([0x21]) + b"GHIJKLM") is None

    try:
        rx.feed(bytes([0x23]) + b"NOPQRST")             # skipped SN 2
    except isotp.IsoTpError:
        pass
    else:
        raise AssertionError("a skipped sequence number must be rejected")


# @req REQ-203
def test_isotp_round_trip():
    """Anything sent must come back byte for byte, at every length that
    changes which frame types are involved."""
    for size in (1, 6, 7, 8, 13, 14, 15, 100, 512):
        wire, rx = [], isotp.IsoTpRx()
        tx = isotp.IsoTpTx()
        payload = bytes(range(256)) * 3
        payload = payload[:size]

        if not tx.start(payload, wire.append):
            tx.on_flow_control(wire.append)

        out = None
        for frame in wire:
            out = rx.feed(frame) or out
        assert out == payload, f"round trip failed at {size} bytes"


if __name__ == "__main__":
    test_session()
    test_isotp_catches_a_dropped_frame()
    test_isotp_round_trip()
    print("all assertions passed")
