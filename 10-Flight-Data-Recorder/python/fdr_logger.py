"""Crash survivable circular logger, the black box.

Three decisions do all the work:

* **Fixed 32 byte frames.** A slot index is a multiply, and a frame that
  was half written cannot shift everything after it.
* **Explicit serialisation**, never a raw struct dump. Padding and
  endianness differ between the recorder and whatever machine reads the
  store afterwards, which is exactly the machine that matters after an
  accident.
* **A CRC per frame, not per file.** One torn frame costs one frame. A
  whole-file checksum would cost the entire recording.

    python python/fdr_logger.py
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

MAGIC = 0x46445231           # "FDR1"
PAYLOAD_MAX = 16
FRAME_BYTES = 32

SOURCE_CAN = 0
SOURCE_ARINC = 1
SOURCE_EVENT = 2
SOURCE_NAMES = {SOURCE_CAN: "CAN", SOURCE_ARINC: "ARINC429", SOURCE_EVENT: "event"}

# magic, timestamp, source, payload_len, payload. The CRC is appended
# separately because it is computed over exactly these 30 bytes.
_BODY = struct.Struct("<IQBB16s")
assert _BODY.size == 30


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass
class Frame:
    timestamp_us: int
    source: int
    payload: bytes

    def pack(self) -> bytes:
        body = _BODY.pack(MAGIC, self.timestamp_us, self.source,
                          len(self.payload), self.payload.ljust(PAYLOAD_MAX, b"\0"))
        return body + struct.pack("<H", crc16(body))

    @classmethod
    def unpack(cls, raw: bytes) -> Frame | None:
        """None means this slot cannot be trusted, for any reason."""
        if len(raw) != FRAME_BYTES:
            return None
        magic, timestamp, source, length, payload = _BODY.unpack(raw[:30])
        # The magic tells a written slot from an empty one, and lets the
        # decoder resync after a run of corruption.
        if magic != MAGIC:
            return None
        if struct.unpack("<H", raw[30:])[0] != crc16(raw[:30]):
            return None
        if length > PAYLOAD_MAX:
            return None
        return cls(timestamp, source, payload[:length])


class FdrLogger:
    def __init__(self, path: str | Path, capacity_frames: int,
                 clock: Callable[[], int] | None = None) -> None:
        if capacity_frames <= 0:
            raise ValueError("an FDR needs a capacity")
        self.path = Path(path)
        self.capacity = capacity_frames
        self._counter = 0
        self.clock = clock or self._builtin_clock

        # A real FDR has a hard, certified, fixed capacity. The store is
        # sized once and never grows, so a full disk can never be the
        # reason a recording stops.
        if not self.path.exists():
            self.path.write_bytes(b"\0" * (FRAME_BYTES * capacity_frames))
        elif self.path.stat().st_size < FRAME_BYTES * capacity_frames:
            with self.path.open("ab") as fh:
                fh.write(b"\0" * (FRAME_BYTES * capacity_frames - self.path.stat().st_size))

        self.file = self.path.open("r+b")
        self.next_slot = self._resume_point()

    def _builtin_clock(self) -> int:
        import time
        # Wall clock plus a counter, so timestamps stay strictly
        # increasing even when several frames land in the same second.
        self._counter += 1
        return int(time.time() * 1_000_000) + self._counter

    def _resume_point(self) -> int:
        """The slot after the newest valid frame.

        Without this, a power cycle would overwrite the most recent data
        first, which is the data anyone actually wants.
        """
        newest, slot_after = -1, 0
        for slot, frame in enumerate(self._iter_slots()):
            if frame and frame.timestamp_us >= newest:
                newest = frame.timestamp_us
                slot_after = (slot + 1) % self.capacity
        return slot_after

    def _iter_slots(self) -> Iterator[Frame | None]:
        with self.path.open("rb") as fh:
            for _ in range(self.capacity):
                raw = fh.read(FRAME_BYTES)
                if len(raw) != FRAME_BYTES:
                    return
                yield Frame.unpack(raw)

    def append(self, source: int, payload: bytes) -> None:
        frame = Frame(self.clock(), source, payload[:PAYLOAD_MAX])
        self.file.seek(self.next_slot * FRAME_BYTES)
        self.file.write(frame.pack())
        # Flushed on every append. Buffering would trade the last few
        # seconds of the recording for throughput, and those seconds are
        # the entire reason the box exists.
        self.file.flush()

        # When full, overwrite the oldest. An FDR keeps the most recent N
        # hours; it never stops recording because it filled up.
        self.next_slot = (self.next_slot + 1) % self.capacity

    def close(self) -> None:
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def replay(path: str | Path) -> tuple[list[Frame], int]:
    """Returns (frames in chronological order, frames discarded).

    The discard count matters: a silently shorter timeline is the worst
    possible outcome for a recorder.
    """
    data = Path(path).read_bytes()
    frames, discarded = [], 0

    for offset in range(0, len(data) - FRAME_BYTES + 1, FRAME_BYTES):
        raw = data[offset:offset + FRAME_BYTES]
        # An all zero slot was simply never written. A slot with content
        # that fails to unpack is a torn write, and worth counting.
        if not any(raw):
            continue
        frame = Frame.unpack(raw)
        if frame is None:
            discarded += 1
        else:
            frames.append(frame)

    # The ring wraps, so slot order is not time order.
    frames.sort(key=lambda f: f.timestamp_us)
    return frames, discarded


def demo() -> None:
    path = Path(__file__).resolve().parent.parent / "fdr_store.bin"
    path.unlink(missing_ok=True)

    tick = iter(range(1000, 1_000_000, 1000))
    with FdrLogger(path, capacity_frames=8, clock=lambda: next(tick)) as fdr:
        for i in range(1, 21):
            source = SOURCE_CAN if i % 2 else SOURCE_ARINC
            fdr.append(source, i.to_bytes(2, "little"))

    frames, discarded = replay(path)
    print(f"wrote 20 frames into a store that holds 8")
    print(f"replayed {len(frames)}, discarded {discarded}\n")
    for frame in frames:
        value = int.from_bytes(frame.payload, "little")
        print(f"  t={frame.timestamp_us:>7} us  {SOURCE_NAMES[frame.source]:<9} value {value}")

    # Now break one frame and show that only that frame is lost.
    raw = bytearray(path.read_bytes())
    raw[3 * FRAME_BYTES + 15] ^= 0xFF
    path.write_bytes(raw)

    frames, discarded = replay(path)
    print(f"\nafter flipping one byte: {len(frames)} frames recovered, {discarded} discarded")
    path.unlink(missing_ok=True)


if __name__ == "__main__":
    demo()
