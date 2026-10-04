from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from busbench.arinc653.scheduler import (ConfigError, Partition, Scheduler,      # noqa: E402
                             build_demo)


def noop():
    pass


# @req REQ-801
def test_overlapping_slices_are_rejected():
    """Two partitions owning the same microsecond is the one thing this
    design exists to make impossible."""
    try:
        Scheduler([Partition("A", 0, 10, noop, 0),
                   Partition("B", 5, 10, noop, 1)], 40)
    except ConfigError:
        return
    raise AssertionError("overlapping partitions must be rejected")


# @req REQ-801
def test_slice_past_the_frame_end_is_rejected():
    try:
        Scheduler([Partition("A", 30, 20, noop, 0)], 40)
    except ConfigError:
        return
    raise AssertionError("a slice running past the frame end must be rejected")


# @req REQ-802
def test_a_hung_partition_only_hurts_itself():
    sched, log = build_demo()
    sched.run(frames=3)

    # Every partition ran every frame, including the two after the one
    # that never finished.
    assert log["fms_runs"] == 3
    assert log["greedy_runs"] == 3
    assert log["nosy_runs"] == 3

    # The greedy partition was cut off every time, and only its own
    # counter moved.
    assert sched.health["GREEDY"].overruns == 3
    assert sched.health["FMS"].overruns == 0
    assert sched.health["NOSY"].overruns == 0

    # The proof: NOSY still started exactly on its offset in the last
    # frame, even though the partition before it ran off the end.
    assert log["nosy_start"] == 2 * 40 + 15


# @req REQ-803
def test_cross_partition_access_is_refused():
    sched, log = build_demo()
    sched.run(frames=3)

    # One read plus one write refused per frame.
    assert sched.health["NOSY"].violations == 6

    # FMS memory still holds what FMS wrote, not the 999 NOSY tried.
    assert log["fms_readback"] == 2
    assert sched.regions[0][0] == 3
    assert sched.regions[2][0] == 42        # its own region, allowed


# @req REQ-803
def test_access_outside_a_slice_is_refused():
    """Nothing may touch partitioned memory when no partition is running."""
    sched, _ = build_demo()
    assert sched.read(0, 0) is None
    assert not sched.write(0, 0, 1)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all assertions passed")
