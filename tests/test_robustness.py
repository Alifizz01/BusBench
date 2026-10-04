"""Property and robustness tests: thousands of random inputs per parser,
checked against an independent reference or against "fails cleanly".

Deterministic seeds, standard library only, so a failure always reproduces.
The C parsers get the same treatment under libFuzzer in CI (see fuzz/).
"""
import random

from busbench.arinc429 import analyzer as a429
from busbench.can.decoder import CanFrame, DbcSignal, decode, signal_bits
from busbench.doip import gateway as doip
from busbench.fdr.recorder import FRAME_BYTES, Frame
from busbench.mil1553.bus import CommandWord
from busbench.uds.isotp import IsoTpError, IsoTpRx, IsoTpTx

N = 3000


def _reference_raw(data: bytes, sig: DbcSignal) -> int:
    """Textbook extraction, written independently of decoder.py's bit walk."""
    mask = (1 << sig.length_bits) - 1
    if sig.little_endian:
        return (int.from_bytes(data, "little") >> sig.start_bit) & mask
    msb = (sig.start_bit // 8) * 8 + (7 - sig.start_bit % 8)     # position in a big-endian bit stream
    return (int.from_bytes(data, "big") >> (64 - msb - sig.length_bits)) & mask


# @req REQ-102
def test_can_decode_matches_reference_for_random_signals():
    rng = random.Random(1)
    checked = 0
    while checked < N:
        sig = DbcSignal("s", 0x100, rng.randrange(64), rng.randint(1, 32), rng.random() < 0.5, False)
        data = bytes(rng.randrange(256) for _ in range(8))
        value = decode(sig, CanFrame(0x100, data))
        if not signal_bits(sig):          # does not fit in 8 bytes: must be refused, not wrapped
            assert value is None
            continue
        assert value == _reference_raw(data, sig), sig
        checked += 1


# @req REQ-102
def test_zero_length_and_oversized_signals_are_refused():
    """Regression: libFuzzer found the C decoder shifting by -1 here."""
    frame = CanFrame(0x100, bytes(8))
    for length in (0, 65):
        for little in (True, False):
            assert decode(DbcSignal("s", 0x100, 7, length, little, True), frame) is None


# @req REQ-203
def test_isotp_round_trips_every_length_and_survives_garbage():
    for size in range(1, 300):
        payload = bytes((i * 7 + size) & 0xFF for i in range(size))
        wire = []
        tx, rx = IsoTpTx(), IsoTpRx()
        if not tx.start(payload, wire.append):
            tx.on_flow_control(wire.append)
        out = None
        for frame in wire:
            out = rx.feed(frame) or out
        assert out == payload
    rng = random.Random(2)
    rx = IsoTpRx()
    for _ in range(N):                  # random frames: either a result, None, or IsoTpError
        frame = bytes(rng.randrange(256) for _ in range(rng.randint(1, 8)))
        try:
            rx.feed(frame)
        except IsoTpError:
            rx = IsoTpRx()


# @req REQ-501
def test_doip_gateway_answers_any_bytes_with_a_wellformed_message():
    rng = random.Random(3)
    gw = doip.Gateway(doip.tiny_ecu)
    for _ in range(N):
        n = rng.randint(0, 40)
        msg = bytes(rng.randrange(256) for _ in range(n))
        if rng.random() < 0.5 and n >= 8:          # half the time, a valid header that may lie
            msg = doip.build(rng.choice([1, 5, 0x8001, 0x4444]), msg[8:])
            if rng.random() < 0.3:
                msg = msg[:-1]
        reply = gw.handle(msg)
        if reply is not None:
            ptype, length = doip.parse_header(reply)
            assert len(reply) == doip.HEADER_LEN + length


# @req REQ-602
def test_arinc429_build_then_analyze_round_trips():
    rng = random.Random(4)
    for _ in range(N):
        bits = rng.randint(1, 19)
        label = rng.randrange(256)
        raw = rng.randrange(-(1 << (bits - 1)), 1 << (bits - 1))
        word = a429.build_word(label, rng.randrange(4), raw & ((1 << bits) - 1), 3, bits)
        assert a429.check_parity(word)
        assert a429.get_label(word) == label
        entry = a429.Label(label, "X", "", 1.0, bits)
        _, value = a429.analyze(word, {label: entry})
        assert value == raw


# @req REQ-701
def test_mil1553_command_word_round_trips_for_all_16_bit_patterns():
    for raw in range(1 << 16):
        cmd = CommandWord.decode(raw)
        assert cmd.encode() == raw


# @req REQ-1002
def test_fdr_never_trusts_a_damaged_frame():
    rng = random.Random(5)
    good = Frame(123456, 1, b"\x01\x02\x03").pack()
    for _ in range(N):
        damaged = bytearray(good)
        damaged[rng.randrange(FRAME_BYTES)] ^= 1 << rng.randrange(8)   # any single bit flip
        assert Frame.unpack(bytes(damaged)) is None
    for _ in range(N):
        assert Frame.unpack(bytes(rng.randrange(256) for _ in range(FRAME_BYTES))) is None


# @req REQ-1001
def test_fdr_random_payloads_round_trip():
    rng = random.Random(6)
    for _ in range(1500):
        payload = bytes(rng.randrange(256) for _ in range(rng.randint(0, 16)))
        frame = Frame(rng.randrange(1 << 63), rng.randrange(3), payload)
        assert Frame.unpack(frame.pack()) == frame
