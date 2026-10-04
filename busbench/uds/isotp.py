"""ISO-TP (ISO 15765-2): a UDS message of up to 4095 bytes carried over
CAN frames that hold 8.

Four frame types do the whole job::

    Single Frame   0x0L                 payload fits in one frame
    First Frame    0x1L LL              start of a long message
    Flow Control   0x30 BS STmin        receiver says "go ahead"
    Consecutive    0x2N                 N is a wrapping 1..15 counter

The sequence number is the point of the protocol: it is how the receiver
notices a dropped frame instead of silently gluing together a corrupt
message.
"""

from __future__ import annotations

from collections.abc import Callable

MAX_PAYLOAD = 512          # the standard allows 4095, this is enough here
POLL_LIMIT = 64            # the simulated bus is synchronous, so this only
                           # trips when the peer really said nothing

SF, FF, CF, FC = 0x00, 0x10, 0x20, 0x30

SendFrame = Callable[[bytes], None]
RecvFrame = Callable[[], "bytes | None"]


class IsoTpError(Exception):
    """Raised on a protocol violation, such as a gap in the sequence."""


def _flow_control() -> bytes:
    # continue to send, block size 0 (no further flow control), STmin 0
    return bytes([FC, 0x00, 0x00])


class IsoTpRx:
    """Reassembles one incoming direction, one CAN frame at a time."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.total = 0
        self.next_sn = 1
        self.active = False

    def feed(self, frame: bytes, send: SendFrame | None = None) -> bytes | None:
        """Returns the complete message, or None if more frames are needed."""
        if not frame:
            raise IsoTpError("empty frame")
        kind = frame[0] & 0xF0

        if kind == SF:
            n = frame[0] & 0x0F
            if not 1 <= n <= 7 or len(frame) < n + 1:
                raise IsoTpError("bad single frame length")
            self.active = False
            return bytes(frame[1:1 + n])

        if kind == FF:
            if len(frame) < 2:
                raise IsoTpError("truncated first frame")
            total = ((frame[0] & 0x0F) << 8) | frame[1]
            if not 8 <= total <= MAX_PAYLOAD:
                raise IsoTpError(f"first frame length {total} out of range")
            self.buf = bytearray(frame[2:8])
            self.total = total
            self.next_sn = 1
            self.active = True
            if send:
                send(_flow_control())
            return None

        if kind == CF:
            if not self.active:
                raise IsoTpError("consecutive frame with no first frame")
            # A mismatched sequence number means a frame was lost. Better
            # to fail loudly than return a message with a hole in it.
            if (frame[0] & 0x0F) != self.next_sn:
                raise IsoTpError(f"expected SN {self.next_sn}, got {frame[0] & 0x0F}")
            self.next_sn = (self.next_sn + 1) & 0x0F
            self.buf += frame[1:1 + (self.total - len(self.buf))]
            if len(self.buf) >= self.total:
                self.active = False
                return bytes(self.buf)
            return None

        return None        # flow control belongs to the transmit side


class IsoTpTx:
    """Sends one outgoing message, pausing for flow control if it is long."""

    def __init__(self) -> None:
        self.buf = b""
        self.sent = 0
        self.sn = 1
        self.active = False

    def start(self, data: bytes, send: SendFrame) -> bool:
        """Returns True if the message went out complete in one frame."""
        if not data or len(data) > MAX_PAYLOAD:
            raise IsoTpError(f"payload of {len(data)} bytes cannot be sent")

        if len(data) <= 7:
            send(bytes([SF | len(data)]) + data)
            self.active = False
            return True

        self.buf, self.sent, self.sn, self.active = data, 6, 1, True
        send(bytes([FF | (len(data) >> 8), len(data) & 0xFF]) + data[:6])
        return False

    def on_flow_control(self, send: SendFrame) -> None:
        while self.active and self.sent < len(self.buf):
            chunk = self.buf[self.sent:self.sent + 7]
            send(bytes([CF | self.sn]) + chunk)
            self.sn = (self.sn + 1) & 0x0F
            self.sent += len(chunk)
        self.active = False


def send_blocking(data: bytes, send: SendFrame, recv: RecvFrame) -> None:
    """Client side send. Unlike an ECU, a tester may sit and wait."""
    tx = IsoTpTx()
    if tx.start(data, send):
        return

    for _ in range(POLL_LIMIT):
        frame = recv()
        if frame and (frame[0] & 0xF0) == FC:
            if (frame[0] & 0x0F) == 0x02:
                raise IsoTpError("peer signalled buffer overflow")
            tx.on_flow_control(send)
            return
    raise TimeoutError("no flow control from peer")


def recv_blocking(send: SendFrame, recv: RecvFrame) -> bytes:
    rx = IsoTpRx()
    for _ in range(POLL_LIMIT):
        frame = recv()
        if frame is None:
            continue
        message = rx.feed(frame, send)
        if message is not None:
            return message
    raise TimeoutError("no response from peer")
