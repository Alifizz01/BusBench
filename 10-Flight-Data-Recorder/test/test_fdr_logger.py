import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import fdr_logger as fdr                                   # noqa: E402
from fdr_logger import FdrLogger, Frame, replay            # noqa: E402

STORE = ROOT / "test_store.bin"


def fresh_clock():
    ticks = iter(range(1000, 10_000_000, 1000))            # 1 ms per frame
    return lambda: next(ticks)


def write(capacity, values, source=fdr.SOURCE_CAN, clock=None, fresh=True):
    if fresh:
        STORE.unlink(missing_ok=True)
    with FdrLogger(STORE, capacity, clock=clock or fresh_clock()) as log:
        for v in values:
            log.append(source, v.to_bytes(2, "little"))


def values_of(frames):
    return [int.from_bytes(f.payload, "little") for f in frames]


def test_crc_matches_the_known_vector():
    """The C decoder must agree byte for byte, so the standard check
    value is pinned here."""
    assert fdr.crc16(b"123456789") == 0x29B1


def test_write_and_replay_in_order():
    write(8, range(1, 6))
    frames, discarded = replay(STORE)
    assert values_of(frames) == [1, 2, 3, 4, 5]
    assert discarded == 0
    assert [f.timestamp_us for f in frames] == sorted(f.timestamp_us for f in frames)


def test_ring_keeps_the_newest_and_stays_chronological():
    """An FDR never stops recording because it filled up, and the replay
    has to be in time order even though the ring wrapped."""
    write(8, range(1, 21))
    frames, _ = replay(STORE)
    assert len(frames) == 8
    assert values_of(frames) == [13, 14, 15, 16, 17, 18, 19, 20]


def test_reopening_resumes_after_the_newest_frame():
    """Restarting must not stamp on the most recent data, which is
    exactly the data anyone wants."""
    write(8, range(1, 21))
    ticks = iter(range(100_000, 200_000, 1000))
    write(8, [21], clock=lambda: next(ticks), fresh=False)

    frames, _ = replay(STORE)
    assert values_of(frames)[-1] == 21
    assert values_of(frames)[0] == 14              # the oldest one rolled off


def test_one_flipped_byte_costs_exactly_one_frame():
    write(8, range(1, 9))
    raw = bytearray(STORE.read_bytes())
    raw[3 * fdr.FRAME_BYTES + 15] ^= 0xFF          # inside slot 3's payload
    STORE.write_bytes(raw)

    frames, discarded = replay(STORE)
    assert len(frames) == 7
    assert discarded == 1


def test_a_torn_final_frame_is_skipped_not_misread():
    """Power loss mid record is the exact scenario this format exists for."""
    write(4, [100, 200])
    raw = bytearray(STORE.read_bytes())
    raw[fdr.FRAME_BYTES:fdr.FRAME_BYTES + 10] = b"\xab" * 10   # half a frame
    STORE.write_bytes(raw)

    frames, discarded = replay(STORE)
    assert values_of(frames) == [100]
    assert discarded == 1


def test_a_frame_survives_a_round_trip_through_bytes():
    """Explicit serialisation, so the store reads the same on any machine."""
    original = Frame(timestamp_us=123456789, source=fdr.SOURCE_ARINC, payload=b"\x01\x02\x03")
    raw = original.pack()
    assert len(raw) == fdr.FRAME_BYTES
    assert Frame.unpack(raw) == original


def test_an_empty_slot_is_not_a_frame():
    assert Frame.unpack(b"\0" * fdr.FRAME_BYTES) is None


if __name__ == "__main__":
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_"):
                fn()
        print("all assertions passed")
    finally:
        STORE.unlink(missing_ok=True)
