"""CAN bus sniffer and DBC decoder.

Same job as the C version in src/, written the way you would actually
reach for it at a desk: read a candump log, read a DBC, print the bus in
engineering units.

    python -m busbench.can.decoder busbench/can/data/example.dbc busbench/can/data/example.log
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

# " SG_ EngineSpeed : 0|16@1+ (0.25,0) [0|16383.75] "rpm" Vector__XXX "
SG_RE = re.compile(
    r'\s*SG_\s+(?P<name>\w+)\s*:\s*'
    r'(?P<start>\d+)\|(?P<length>\d+)@(?P<order>[01])(?P<sign>[+-])\s*'
    r'\((?P<scale>[^,]+),(?P<offset>[^)]+)\)'
    r'(?:\s*\[[^\]]*\])?'
    r'(?:\s*"(?P<unit>[^"]*)")?'
)
BO_RE = re.compile(r'\s*BO_\s+(?P<id>\d+)\s+(?P<name>\w+)\s*:')


@dataclass
class CanFrame:
    can_id: int
    data: bytes
    timestamp_us: int = 0

    @property
    def dlc(self) -> int:
        return len(self.data)


@dataclass
class DbcSignal:
    name: str
    can_id: int
    start_bit: int
    length_bits: int
    little_endian: bool
    is_signed: bool
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    message: str = field(default="", compare=False)


def _bit(data: bytes, i: int) -> int:
    """DBC bit numbering: bit i is in byte i//8, at bit i%8 counting from
    that byte's least significant bit."""
    return (data[i >> 3] >> (i & 7)) & 1


def load_dbc(path: str) -> list[DbcSignal]:
    signals: list[DbcSignal] = []
    current_id, current_msg = 0, ""

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            bo = BO_RE.match(line)
            if bo:
                current_id = int(bo["id"])
                current_msg = bo["name"]
                continue

            sg = SG_RE.match(line)
            if not sg:
                continue
            length = int(sg["length"])
            if not 1 <= length <= 64:
                continue           # malformed line, skip rather than crash
            signals.append(DbcSignal(
                name=sg["name"],
                can_id=current_id,
                start_bit=int(sg["start"]),
                length_bits=length,
                little_endian=sg["order"] == "1",
                is_signed=sg["sign"] == "-",
                scale=float(sg["scale"]),
                offset=float(sg["offset"]),
                unit=sg["unit"] or "",
                message=current_msg,
            ))
    return signals


def decode(sig: DbcSignal, frame: CanFrame) -> float | None:
    """Physical value of one signal, or None if this frame is not its."""
    if sig.can_id != frame.can_id:
        return None
    # Same guard as the C version, where libFuzzer found a zero-length
    # signal shifting by -1. Here it would raise instead of decoding.
    if not 1 <= sig.length_bits <= 64:
        return None

    total_bits = frame.dlc * 8
    raw = 0

    if sig.little_endian:
        # Intel: bits run upward from start_bit, least significant first.
        if sig.start_bit + sig.length_bits > total_bits:
            return None
        for k in range(sig.length_bits):
            raw |= _bit(frame.data, sig.start_bit + k) << k
    else:
        # Motorola: start_bit is the most significant bit. Walk downward
        # inside the byte, then jump to the top bit of the next byte.
        pos = sig.start_bit
        for _ in range(sig.length_bits):
            if not 0 <= pos < total_bits:
                return None
            raw = (raw << 1) | _bit(frame.data, pos)
            pos = pos + 15 if pos % 8 == 0 else pos - 1

    if sig.is_signed and raw >> (sig.length_bits - 1):
        raw -= 1 << sig.length_bits          # two's complement

    return raw * sig.scale + sig.offset


def signal_bits(sig: DbcSignal, dlc: int = 8) -> list[int]:
    """DBC bit positions the signal occupies, least significant first.

    Same walk as ``decode``: Intel climbs upward from start_bit, Motorola
    starts at its most significant bit and steps down through each byte,
    jumping to the top of the next byte. Returns [] if it does not fit.
    """
    total = dlc * 8
    if sig.little_endian:
        bits = [sig.start_bit + k for k in range(sig.length_bits)]
    else:
        bits, pos = [], sig.start_bit
        for _ in range(sig.length_bits):
            bits.append(pos)
            pos = pos + 15 if pos % 8 == 0 else pos - 1
        bits.reverse()
    return bits if all(0 <= b < total for b in bits) else []


LOG_RE = re.compile(r'\s*\((?P<ts>[\d.]+)\)\s+(?P<iface>\S+)\s+(?P<id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)')


def read_log(path: str) -> list[CanFrame]:
    """Reads the format `candump -l` writes, so no CAN hardware is needed."""
    frames = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = LOG_RE.match(line)
            if not m:
                continue
            hexstr = m["data"]
            if len(hexstr) % 2:
                hexstr = hexstr[:-1]         # truncated log line
            frames.append(CanFrame(
                can_id=int(m["id"], 16),
                data=bytes.fromhex(hexstr)[:8],
                timestamp_us=int(float(m["ts"]) * 1e6),
            ))
    return frames


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 1
    signals = load_dbc(argv[1])
    frames = read_log(argv[2])
    print(f"loaded {len(signals)} signals, {len(frames)} frames\n")

    for frame in frames:
        print(f"[{frame.timestamp_us} us] ID 0x{frame.can_id:03X}:")
        for sig in signals:
            value = decode(sig, frame)
            if value is not None:
                print(f"    {sig.name:<14} {value:10.2f} {sig.unit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
