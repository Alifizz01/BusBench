"""Checks the Python decoder against the same known-good frames the C
test uses, so the two implementations cannot silently disagree."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from busbench.can.decoder import CanFrame, decode, load_dbc, read_log   # noqa: E402


# @req REQ-101
def test_dbc_decoding_intel_and_motorola():
    signals = load_dbc(ROOT / "data" / "example.dbc")
    frames = read_log(ROOT / "data" / "example.log")
    assert len(signals) == 5, len(signals)
    assert len(frames) == 4, len(frames)

    by_name = {s.name: s for s in signals}

    # Endianness and sign have to come out of the "@0-" style flags.
    assert by_name["EngineSpeed"].little_endian
    assert not by_name["EngineSpeed"].is_signed
    assert not by_name["SteeringAngle"].little_endian
    assert by_name["SteeringAngle"].is_signed

    assert decode(by_name["EngineSpeed"], frames[0]) == 2000.0      # Intel
    assert decode(by_name["CoolantTemp"], frames[0]) == 90.0        # Intel + offset
    assert decode(by_name["VehicleSpeed"], frames[1]) == 100.0      # Motorola
    assert decode(by_name["SteeringAngle"], frames[1]) == -45.0     # Motorola + signed

    # A signal never decodes from another message's ID.
    assert decode(by_name["EngineSpeed"], frames[1]) is None

    # A short frame must be refused, not read past its end.
    short = CanFrame(can_id=256, data=b"\x40")
    assert decode(by_name["CoolantTemp"], short) is None

    print("all assertions passed")


if __name__ == "__main__":
    test_dbc_decoding_intel_and_motorola()
