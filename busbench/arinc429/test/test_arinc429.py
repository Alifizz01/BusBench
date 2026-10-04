from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from busbench.arinc429 import analyzer as a429

DICT = a429.load_dictionary(ROOT / "data" / "labels.csv")


# @req REQ-601
def test_label_is_reversed_on_the_wire():
    """Getting this wrong gives a plausible looking label for the wrong
    parameter entirely, which is worse than an obvious error."""
    word = a429.build_word(0o203, 1, 35000, a429.SSM_NORMAL_OPERATION, 18)
    assert word & 0xFF == 0xC1              # 0203 octal reversed
    assert a429.get_label(word) == 0o203
    assert a429.get_sdi(word) == 1


# @req REQ-601
def test_odd_parity_catches_a_flipped_bit():
    word = a429.build_word(0o203, 1, 35000, a429.SSM_NORMAL_OPERATION, 18)
    assert a429.check_parity(word)
    for bit in (0, 3, 12, 20, 28, 31):
        assert not a429.check_parity(word ^ (1 << bit))


# @req REQ-602
def test_round_trip_at_several_widths():
    for label, raw, bits, expected in [
        (0o203, 35000, 18, 35000.0),        # altitude, 1 ft per count
        (0o210, 7680, 15, 480.0),           # airspeed, 0.0625 kt per count
        (0o320, 35900, 17, 359.0),          # heading, 0.01 deg per count
    ]:
        word = a429.build_word(label, 1, raw, a429.SSM_NORMAL_OPERATION, bits)
        entry, value = a429.analyze(word, DICT)
        assert abs(value - expected) < 1e-6, (entry.name, value)


# @req REQ-602
def test_negative_values_are_twos_complement():
    word = a429.build_word(0o212, 1, -2000, a429.SSM_NORMAL_OPERATION, 16)
    entry, value = a429.analyze(word, DICT)
    assert entry.name == "VERT_SPEED"
    assert value == -2000.0


# @req REQ-603
def test_a_word_can_decode_and_still_be_unusable():
    """The SSM is not a decoding failure, so analyze still returns a
    number. Using it anyway is the bug."""
    word = a429.build_word(0o210, 1, 7680, a429.SSM_NO_COMPUTED_DATA, 15)
    assert a429.analyze(word, DICT) is not None
    assert not a429.is_usable(word)


# @req REQ-602
def test_unknown_label_is_refused_not_guessed():
    word = a429.build_word(0o377, 0, 1, a429.SSM_NORMAL_OPERATION, 18)
    assert a429.analyze(word, DICT) is None


# @req REQ-604
def test_capture_file_matches_the_c_implementation():
    """The same capture the C test reads, decoded to the same values.
    The two implementations cannot drift apart without this failing."""
    words = a429.read_capture(ROOT / "data" / "capture.txt")
    assert len(words) == 6

    decoded = []
    for word in words:
        result = a429.analyze(word, DICT)
        decoded.append(None if result is None else (result[0].name, result[1]))

    assert decoded[0] == ("ALTITUDE", 35000.0)
    assert decoded[1] == ("AIRSPEED", 480.0)
    assert decoded[2] == ("VERT_SPEED", -2000.0)
    assert decoded[3] == ("HEADING", 359.0)
    assert not a429.is_usable(words[4])       # decodes, but SSM says do not use
    assert decoded[5] is None                 # parity error, discarded


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all assertions passed")
