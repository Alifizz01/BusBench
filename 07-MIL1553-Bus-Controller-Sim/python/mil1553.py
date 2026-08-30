"""MIL-STD-1553 bus controller and the remote terminals it polls.

Unlike ARINC 429, nothing on a 1553 bus happens unless the bus controller
asks for it. There is no arbitration and no RT ever speaks first, which
is exactly why it is used where timing has to be provable.

Command word, 16 bits::

    15 .. 11    10     9 .. 5        4 .. 0
    RT address  T/R    subaddress    word count or mode code

    python python/mil1553.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

BROADCAST_ADDRESS = 31           # every RT listens, none answers
MODE_SUBADDRESSES = (0, 31)      # here the low five bits are a mode code
MODE_TRANSMIT_STATUS = 0x02
MODE_RESET_RT = 0x08

STATUS_MESSAGE_ERROR = 1 << 10
STATUS_SERVICE_REQUEST = 1 << 8
STATUS_BROADCAST_RCVD = 1 << 4
STATUS_BUSY = 1 << 3
STATUS_SUBSYSTEM_FLAG = 1 << 2
STATUS_TERMINAL_FLAG = 1 << 0

MAX_WORDS = 32


@dataclass
class CommandWord:
    rt_address: int
    tr: int                      # 1 = transmit (RT to BC), 0 = receive
    subaddress: int
    word_count: int

    @property
    def is_mode_code(self) -> bool:
        return self.subaddress in MODE_SUBADDRESSES

    def encode(self) -> int:
        # Word count 32 goes on the wire as 0. Five bits have to cover a
        # count that runs 1 to 32, so 32 borrows the unused zero.
        count_field = 0 if self.word_count >= 32 else self.word_count & 0x1F
        return ((self.rt_address & 0x1F) << 11 | (self.tr & 1) << 10
                | (self.subaddress & 0x1F) << 5 | count_field)

    @classmethod
    def decode(cls, raw: int) -> CommandWord:
        subaddress = (raw >> 5) & 0x1F
        count_field = raw & 0x1F
        # On a mode-code subaddress those five bits are the mode code, so
        # they must not be turned into a word count of 32.
        word_count = count_field
        if subaddress not in MODE_SUBADDRESSES and count_field == 0:
            word_count = 32
        return cls((raw >> 11) & 0x1F, (raw >> 10) & 1, subaddress, word_count)


@dataclass
class StatusWord:
    rt_address: int = 0
    message_error: bool = False
    busy: bool = False
    flags: int = 0


class Timeout(Exception):
    """No answer at all. There is no negative acknowledge on 1553."""


class TransactionError(Exception):
    """The RT answered, but not with usable data."""


@dataclass
class RemoteTerminal:
    connected: bool = True
    busy: bool = False
    subsystem_fault: bool = False
    broadcasts_received: int = 0
    data: dict[int, list[int]] = field(default_factory=dict)


class BusController:
    def __init__(self) -> None:
        self.rts: dict[int, RemoteTerminal] = {}
        self.transactions = 0
        self.retries = 0
        self.failures = 0

    def connect(self, address: int) -> RemoteTerminal:
        rt = self.rts[address] = RemoteTerminal()
        return rt

    def _status(self, rt: RemoteTerminal, address: int, broadcast: bool = False) -> StatusWord:
        flags = 0
        if rt.busy:
            flags |= STATUS_BUSY
        if rt.subsystem_fault:
            flags |= STATUS_SUBSYSTEM_FLAG
        if broadcast:
            flags |= STATUS_BROADCAST_RCVD
        return StatusWord(address, busy=rt.busy, flags=flags)

    def transact(self, cmd: CommandWord, data: list[int] | None = None) -> tuple[list[int], StatusWord]:
        """One BC transaction. Raises rather than returning a flag, so a
        caller cannot use the data buffer after a failure."""
        self.transactions += 1

        if cmd.rt_address == BROADCAST_ADDRESS:
            # Every RT takes the data and NONE of them answers. A BC that
            # waits for a status word here times out every single time, on
            # a bus that is working perfectly.
            for address, rt in self.rts.items():
                if address == BROADCAST_ADDRESS:
                    continue
                rt.broadcasts_received += 1
                if not cmd.is_mode_code and cmd.tr == 0 and data:
                    rt.data[cmd.subaddress] = list(data[:cmd.word_count])
            return [], StatusWord()

        rt = self.rts.get(cmd.rt_address)
        # Nothing at that address means silence, and silence is a timeout.
        if rt is None or not rt.connected:
            self.failures += 1
            raise Timeout(f"no answer from RT {cmd.rt_address}")

        status = self._status(rt, cmd.rt_address)

        # A busy RT answers with the busy bit and no data. The BC has to
        # treat that as "come back later", not as data it can use.
        if rt.busy:
            self.failures += 1
            raise TransactionError(f"RT {cmd.rt_address} is busy")

        if cmd.is_mode_code:
            if cmd.word_count == MODE_RESET_RT:
                rt.subsystem_fault = False
                rt.busy = False
            return [], status

        count = 32 if cmd.word_count == 0 else cmd.word_count
        if count > MAX_WORDS:
            self.failures += 1
            status.message_error = True
            raise TransactionError("word count out of range")

        if cmd.tr:                                  # transmit, RT to BC
            words = rt.data.get(cmd.subaddress, [])
            if len(words) < count:
                # Fewer words than asked for shows up on a real bus as a
                # missing word, which is a message error.
                self.failures += 1
                status.message_error = True
                raise TransactionError(
                    f"RT {cmd.rt_address} sent {len(words)} of {count} words")
            out = words[:count]
        else:                                       # receive, BC to RT
            if data is None or len(data) < count:
                self.failures += 1
                status.message_error = True
                raise TransactionError("not enough data words to send")
            rt.data[cmd.subaddress] = list(data[:count])
            out = []

        if rt.subsystem_fault:
            # The transfer worked, but the RT says its data is not
            # trustworthy. Delivering the words without the flag is how
            # bad data reaches a control law.
            self.failures += 1
            raise TransactionError(f"RT {cmd.rt_address} raised its subsystem flag")

        return out, status

    def run_schedule(self, schedule: list[CommandWord], minor_frame_ms: int = 20) -> None:
        """The fixed major/minor frame. Order is what matters here, not
        the wall clock, so time is not actually slept."""
        for cmd in schedule:
            try:
                self.transact(cmd, [0] * MAX_WORDS)
            except (Timeout, TransactionError):
                # One retry, then move on. A BC must never stall the whole
                # frame for one sulking terminal: every other RT on the bus
                # has a deadline that does not care.
                self.retries += 1
                try:
                    self.transact(cmd, [0] * MAX_WORDS)
                except (Timeout, TransactionError):
                    pass


def demo() -> None:
    bc = BusController()
    bc.connect(3)
    bc.connect(5)

    payload = [0x1111, 0x2222, 0x3333, 0x4444]
    bc.transact(CommandWord(3, tr=0, subaddress=1, word_count=4), payload)
    words, _ = bc.transact(CommandWord(3, tr=1, subaddress=1, word_count=4))
    print("read back from RT 3:", [f"0x{w:04X}" for w in words])

    try:
        bc.transact(CommandWord(9, tr=1, subaddress=1, word_count=4))
    except Timeout as exc:
        print("absent RT          :", exc)

    bc.transact(CommandWord(BROADCAST_ADDRESS, tr=0, subaddress=7, word_count=4), payload)
    print("broadcast received :", {a: rt.broadcasts_received for a, rt in bc.rts.items()})

    bc.run_schedule([
        CommandWord(3, tr=1, subaddress=1, word_count=4),
        CommandWord(9, tr=1, subaddress=1, word_count=4),      # not on the bus
        CommandWord(5, tr=0, subaddress=1, word_count=2),
    ])
    print(f"frame done         : {bc.transactions} transactions, "
          f"{bc.retries} retries, {bc.failures} failures")


if __name__ == "__main__":
    demo()
