from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from busbench.mil1553.bus import (BROADCAST_ADDRESS, MODE_RESET_RT,           # noqa: E402
                     MODE_TRANSMIT_STATUS, STATUS_BUSY, STATUS_SUBSYSTEM_FLAG,
                     BusController, CommandWord, Timeout, TransactionError)


# @req REQ-701
def test_command_word_round_trip():
    cmd = CommandWord(rt_address=5, tr=1, subaddress=9, word_count=4)
    raw = cmd.encode()
    assert raw == (5 << 11) | (1 << 10) | (9 << 5) | 4
    assert CommandWord.decode(raw) == cmd


# @req REQ-701
def test_word_count_32_encodes_as_zero():
    """Five bits have to cover a count that runs 1 to 32, so 32 borrows
    the unused zero."""
    cmd = CommandWord(5, tr=1, subaddress=9, word_count=32)
    assert cmd.encode() & 0x1F == 0
    assert CommandWord.decode(cmd.encode()).word_count == 32


# @req REQ-701
def test_mode_code_subaddress_keeps_its_code():
    """On subaddress 0 or 31 those same five bits are a mode code, so
    they must not become a word count of 32."""
    for sub in (0, 31):
        cmd = CommandWord(5, tr=1, subaddress=sub, word_count=MODE_TRANSMIT_STATUS)
        assert CommandWord.decode(cmd.encode()).word_count == MODE_TRANSMIT_STATUS

        cmd = CommandWord(5, tr=1, subaddress=sub, word_count=0)
        assert CommandWord.decode(cmd.encode()).word_count == 0


# @req REQ-702
def test_write_then_read_back():
    bc = BusController()
    bc.connect(3)
    payload = [0x1111, 0x2222, 0x3333, 0x4444]
    bc.transact(CommandWord(3, tr=0, subaddress=1, word_count=4), payload)
    words, _ = bc.transact(CommandWord(3, tr=1, subaddress=1, word_count=4))
    assert words == payload


# @req REQ-702
def test_absent_rt_times_out():
    """There is no negative acknowledge on 1553, only an answer or none."""
    bc = BusController()
    try:
        bc.transact(CommandWord(12, tr=1, subaddress=1, word_count=4))
    except Timeout:
        return
    raise AssertionError("an absent RT must time out")


# @req REQ-702
def test_busy_rt_gives_no_data():
    bc = BusController()
    rt = bc.connect(5)
    rt.data[1] = [1, 2, 3, 4]
    rt.busy = True
    try:
        bc.transact(CommandWord(5, tr=1, subaddress=1, word_count=4))
    except TransactionError:
        assert bc._status(rt, 5).flags & STATUS_BUSY
        return
    raise AssertionError("a busy RT must not hand over data")


# @req REQ-702
def test_subsystem_fault_is_reported_then_cleared():
    """The transfer works, but the RT says its data is not trustworthy.
    Delivering it without the flag is how bad data reaches a control law."""
    bc = BusController()
    rt = bc.connect(5)
    rt.data[2] = [1, 2, 3, 4]
    rt.subsystem_fault = True

    try:
        bc.transact(CommandWord(5, tr=1, subaddress=2, word_count=4))
    except TransactionError:
        pass
    else:
        raise AssertionError("a subsystem fault must not pass silently")

    assert bc._status(rt, 5).flags & STATUS_SUBSYSTEM_FLAG
    bc.transact(CommandWord(5, tr=0, subaddress=0, word_count=MODE_RESET_RT))
    words, _ = bc.transact(CommandWord(5, tr=1, subaddress=2, word_count=4))
    assert words == [1, 2, 3, 4]


# @req REQ-703
def test_broadcast_reaches_everyone_and_nobody_answers():
    bc = BusController()
    bc.connect(3)
    bc.connect(5)
    payload = [0x1111, 0x2222, 0x3333, 0x4444]

    words, status = bc.transact(
        CommandWord(BROADCAST_ADDRESS, tr=0, subaddress=7, word_count=4), payload)
    assert words == [] and status.rt_address == 0        # no status word at all
    assert bc.rts[3].broadcasts_received == 1
    assert bc.rts[5].broadcasts_received == 1
    assert bc.rts[3].data[7] == payload


# @req REQ-703
def test_one_dead_rt_does_not_stop_the_frame():
    bc = BusController()
    bc.connect(3).data[1] = [1, 2, 3, 4]
    bc.connect(5).data[1] = [9, 9]

    bc.run_schedule([
        CommandWord(3, tr=1, subaddress=1, word_count=4),
        CommandWord(9, tr=1, subaddress=1, word_count=4),    # not on the bus
        CommandWord(5, tr=1, subaddress=1, word_count=2),
    ])

    assert bc.transactions == 4      # three slots plus one retry
    assert bc.retries == 1
    assert bc.failures == 2          # the absent RT, twice


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all assertions passed")
