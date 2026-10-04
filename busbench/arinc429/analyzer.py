"""ARINC 429 bus analyzer: the avionics counterpart to project 1.

A word is 32 bits, using ARINC bit numbers 1 to 32::

    32     31 30    29        29 .. 11        10 9      8 .. 1
    parity |  SSM  | sign |     data      |   SDI   |  label  |

Two things catch everyone out. The label is transmitted most significant
bit first while every other field is least significant bit first, so the
label byte comes out backwards. And parity is odd, not even.

    python -m busbench.arinc429.analyzer [labels.csv capture.txt]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

DATA_SHIFT = 10          # ARINC bit 11 is bit 10 counting from zero
DATA_BITS = 19           # ARINC bits 11 to 29, sign included
DATA_MASK = 0x7FFFF
SIGN_BIT = 0x40000       # bit 29, the top of the data field

# Sign/status matrix for BNR data. Only Normal Operation carries a number
# worth using; the other three say the source knows it cannot give one.
SSM_FAILURE_WARNING = 0
SSM_NO_COMPUTED_DATA = 1
SSM_FUNCTIONAL_TEST = 2
SSM_NORMAL_OPERATION = 3

SSM_NAMES = {
    SSM_FAILURE_WARNING: "failure warning",
    SSM_NO_COMPUTED_DATA: "no computed data",
    SSM_FUNCTIONAL_TEST: "functional test",
    SSM_NORMAL_OPERATION: "normal",
}


@dataclass
class Label:
    label_octal: int
    name: str
    unit: str
    lsb_scale: float
    data_bits: int


def _reverse_byte(b: int) -> int:
    """The label goes out most significant bit first while everything else
    goes least significant bit first, so in an integer it is reversed."""
    return int(f"{b & 0xFF:08b}"[::-1], 2)


def get_label(word: int) -> int:
    return _reverse_byte(word & 0xFF)


def get_sdi(word: int) -> int:
    return (word >> 8) & 0x3


def get_ssm(word: int) -> int:
    return (word >> 29) & 0x3


def check_parity(word: int) -> bool:
    """Odd parity: the whole word, parity bit included, must have an odd
    number of ones. An even count means a bit flipped in flight."""
    return bin(word & 0xFFFFFFFF).count("1") % 2 == 1


def is_usable(word: int) -> bool:
    return get_ssm(word) == SSM_NORMAL_OPERATION


def build_word(label_octal: int, sdi: int, raw_value: int,
               ssm: int, data_bits: int) -> int:
    if not 1 <= data_bits <= DATA_BITS:
        raise ValueError(f"data_bits must be 1 to {DATA_BITS}")

    # BNR data is left justified: the used bits sit at the top of the
    # field and the unused low bits are padding.
    field = (raw_value << (DATA_BITS - data_bits)) & DATA_MASK
    word = (_reverse_byte(label_octal) | (sdi & 3) << 8
            | field << DATA_SHIFT | (ssm & 3) << 29)

    # Set the parity bit so the total count of ones ends up odd.
    if bin(word).count("1") % 2 == 0:
        word |= 0x80000000
    return word


def load_dictionary(path: str | Path) -> dict[int, Label]:
    labels: dict[int, Label] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            continue
        # Labels are written in octal by everyone in avionics, so they are
        # read in octal here rather than silently as decimal.
        octal = int(parts[0], 8)
        labels[octal] = Label(octal, parts[1], parts[2], float(parts[3]), int(parts[4]))
    return labels


def analyze(word: int, dictionary: dict[int, Label]) -> tuple[Label, float] | None:
    """Returns (label, physical value), or None if the word cannot be
    decoded at all. A word that decodes can still be unusable: check
    is_usable separately, because the SSM is not a decoding failure."""
    if not check_parity(word):
        return None
    entry = dictionary.get(get_label(word))
    if entry is None:
        return None

    field = (word >> DATA_SHIFT) & DATA_MASK
    if field & SIGN_BIT:                        # two's complement, bit 29 is sign
        field -= SIGN_BIT << 1

    # Undo the left justification. The pad bits are zero, so this is exact.
    raw = field >> (DATA_BITS - entry.data_bits)
    return entry, raw * entry.lsb_scale


def read_capture(path: str | Path) -> list[int]:
    words = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            words.append(int(line, 16))
    return words


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent
    dict_path = argv[1] if len(argv) > 1 else root / "data" / "labels.csv"
    cap_path = argv[2] if len(argv) > 2 else root / "data" / "capture.txt"

    dictionary = load_dictionary(dict_path)
    for word in read_capture(cap_path):
        if not check_parity(word):
            print(f"  {word:08X}  PARITY ERROR, discarded")
            continue
        result = analyze(word, dictionary)
        if result is None:
            print(f"  {word:08X}  label {get_label(word):03o} not in dictionary")
            continue
        entry, value = result
        note = "" if is_usable(word) else f"<- SSM {SSM_NAMES[get_ssm(word)]}, ignore"
        print(f"  {word:08X}  {entry.name:<11} {value:10.2f} {entry.unit:<7} {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
