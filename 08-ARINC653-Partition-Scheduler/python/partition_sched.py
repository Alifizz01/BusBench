"""ARINC 653 time and space partitioning.

The idea worth taking away: the major frame advances on the clock, not on
partitions finishing. A partition that runs long is cut off at its own
boundary and the next one still starts exactly on its offset. That is
what makes it safe to run a badly behaved partition next to a critical
one, and it is why the schedule is fixed offline rather than computed at
runtime by something that could get it wrong.

    python python/partition_sched.py
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

REGION_WORDS = 16


class ConfigError(Exception):
    """A bad schedule is a build error, not a surprise in the air."""


@dataclass
class Partition:
    name: str
    offset_ms: int
    duration_ms: int
    entry_point: Callable[[], None] | None
    memory_region_id: int


@dataclass
class Health:
    overruns: int = 0
    violations: int = 0


class Scheduler:
    def __init__(self, partitions: list[Partition], major_frame_ms: int) -> None:
        self._validate(partitions, major_frame_ms)
        self.partitions = partitions
        self.major_frame_ms = major_frame_ms
        self.health = {p.name: Health() for p in partitions}
        self.regions: dict[int, list[int]] = {
            p.memory_region_id: [0] * REGION_WORDS for p in partitions
        }
        self.now_ms = 0
        self.frames_run = 0
        self._current: Partition | None = None
        self._budget_left = 0

    @staticmethod
    def _validate(partitions: list[Partition], major_frame_ms: int) -> None:
        if not partitions or major_frame_ms <= 0:
            raise ConfigError("a schedule needs partitions and a frame length")

        for i, p in enumerate(partitions):
            if p.duration_ms <= 0:
                raise ConfigError(f"{p.name} has no time slice")
            # A slice running past the end of the frame would silently eat
            # into the next frame's first partition.
            if p.offset_ms + p.duration_ms > major_frame_ms:
                raise ConfigError(f"{p.name} runs past the end of the major frame")

            for q in partitions[:i]:
                # Overlapping slices mean two partitions think they own the
                # same microsecond, which is the one thing this design
                # exists to make impossible.
                if p.offset_ms < q.offset_ms + q.duration_ms and q.offset_ms < p.offset_ms + p.duration_ms:
                    raise ConfigError(f"{p.name} overlaps {q.name}")

    @property
    def current_name(self) -> str:
        return self._current.name if self._current else ""

    def work(self, ms: int) -> bool:
        """How a partition spends its slice. False means it has been cut off."""
        if self._current is None:
            return False

        if ms > self._budget_left:
            # The slice is over. The partition is told to stop, and the
            # fact that it wanted more is recorded against it and nobody else.
            self.now_ms += self._budget_left
            self._budget_left = 0
            self.health[self._current.name].overruns += 1
            return False

        self._budget_left -= ms
        self.now_ms += ms
        return True

    def _check_access(self, region_id: int, index: int) -> bool:
        if self._current is None or not 0 <= index < REGION_WORDS:
            return False
        # Space partitioning. An MPU would trap this in hardware; here it
        # is refused at the API boundary and logged against whoever tried.
        # Either way the neighbouring memory is untouched.
        if region_id != self._current.memory_region_id:
            self.health[self._current.name].violations += 1
            return False
        return True

    def write(self, region_id: int, index: int, value: int) -> bool:
        if not self._check_access(region_id, index):
            return False
        self.regions[region_id][index] = value
        return True

    def read(self, region_id: int, index: int) -> int | None:
        if not self._check_access(region_id, index):
            return None
        return self.regions[region_id][index]

    def run(self, frames: int = 1) -> None:
        for _ in range(frames):
            frame_start = self.now_ms

            for partition in self.partitions:
                # Each partition starts at its offset, whatever the
                # previous one did with its own slice. This single line is
                # the whole guarantee.
                self.now_ms = frame_start + partition.offset_ms
                self._current = partition
                self._budget_left = partition.duration_ms
                if partition.entry_point:
                    partition.entry_point()
                self._current = None

            self.now_ms = frame_start + self.major_frame_ms
            self.frames_run += 1


def build_demo() -> tuple[Scheduler, dict]:
    """Three partitions of different quality, sharing one CPU."""
    log = {"fms_runs": 0, "greedy_runs": 0, "nosy_runs": 0,
           "fms_readback": None, "nosy_start": None}
    sched: Scheduler

    def flight_management() -> None:
        log["fms_runs"] += 1
        # Read back what this partition itself left here last frame. If
        # the isolation leaks, the 999 from next door shows up instead.
        log["fms_readback"] = sched.read(0, 0)
        sched.work(3)
        sched.write(0, 0, log["fms_runs"])

    def greedy() -> None:
        log["greedy_runs"] += 1
        while sched.work(1):        # keeps asking until it is cut off
            pass

    def nosy() -> None:
        log["nosy_runs"] += 1
        log["nosy_start"] = sched.now_ms
        sched.read(0, 0)            # region 0 belongs to flight management
        sched.write(0, 0, 999)
        sched.write(2, 0, 42)       # its own region, allowed

    sched = Scheduler([
        Partition("FMS", 0, 10, flight_management, 0),
        Partition("GREEDY", 10, 5, greedy, 1),
        Partition("NOSY", 15, 5, nosy, 2),
    ], major_frame_ms=40)

    return sched, log


def demo() -> None:
    sched, log = build_demo()
    sched.run(frames=3)

    print(f"partitions run      : FMS {log['fms_runs']}, "
          f"GREEDY {log['greedy_runs']}, NOSY {log['nosy_runs']}")
    for name, health in sched.health.items():
        print(f"  {name:<7} overruns {health.overruns}  violations {health.violations}")
    print(f"NOSY started at t={log['nosy_start']} ms, exactly its offset")
    print(f"FMS read back {log['fms_readback']}, never the 999 from next door")


if __name__ == "__main__":
    demo()
