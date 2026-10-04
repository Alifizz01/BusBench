"""DoIP gateway (ISO 13400): UDS diagnostics carried over TCP instead of CAN.

Three pieces, deliberately separate:

* ``build`` / ``parse_header`` for the 8 byte framing
* ``Gateway``, the protocol state machine, which touches no sockets
* ``serve`` and ``DoipClient``, the thin TCP layer around it

Keeping the state machine off the network is what makes the awkward cases
(bad version byte, a length field that lies, diagnostics before routing
activation) testable as plain buffers.

    python -m busbench.doip.gateway
"""

from __future__ import annotations

import socket
import struct
import threading
from collections.abc import Callable

VERSION = 0x02              # ISO 13400-2:2012
HEADER_LEN = 8
TCP_PORT = 13400

# Payload types.
GENERIC_NACK = 0x0000
VEHICLE_IDENT_REQ = 0x0001
VEHICLE_IDENT_RESP = 0x0004
ROUTING_ACTIVATION_REQ = 0x0005
ROUTING_ACTIVATION_RESP = 0x0006
DIAG_MESSAGE = 0x8001
DIAG_ACK = 0x8002
DIAG_NACK = 0x8003

# Generic negative acknowledge codes.
NACK_INCORRECT_PATTERN = 0x00
NACK_UNKNOWN_PAYLOAD = 0x01
NACK_MESSAGE_TOO_LARGE = 0x02
NACK_INVALID_LENGTH = 0x04

ROUTING_UNKNOWN_SOURCE = 0x00
ROUTING_SUCCESS = 0x10
DIAG_NACK_UNKNOWN_TARGET = 0x03

TESTER_ADDRESS = 0x0E00
ENTITY_ADDRESS = 0x0010
MAX_PAYLOAD = 4096
VIN = b"WVWZZZ1JZ3W386752"

UdsHandler = Callable[[bytes], bytes]


def build(payload_type: int, payload: bytes = b"") -> bytes:
    return struct.pack(">BBHI", VERSION, VERSION ^ 0xFF, payload_type, len(payload)) + payload


def parse_header(data: bytes) -> tuple[int, int]:
    """Returns (payload_type, payload_length). Raises on a bad header."""
    if len(data) < HEADER_LEN:
        raise ValueError("short header")
    version, inverse, payload_type, length = struct.unpack(">BBHI", data[:HEADER_LEN])
    # Byte 1 must be the complement of byte 0. Cheap, and it catches a
    # stream that is not DoIP at all before anything else is believed.
    if inverse != version ^ 0xFF or version != VERSION:
        raise ValueError("bad protocol version pattern")
    return payload_type, length


class Gateway:
    """The protocol state machine. No sockets, so every case is testable."""

    def __init__(self, uds_handler: UdsHandler | None = None) -> None:
        self.uds_handler = uds_handler
        self.routing_active = False
        self.active_tester = 0

    def reset_session(self) -> None:
        self.routing_active = False
        self.active_tester = 0

    def handle(self, message: bytes) -> bytes | None:
        """One DoIP message in, one out. None means send nothing."""
        try:
            payload_type, length = parse_header(message)
        except ValueError:
            return build(GENERIC_NACK, bytes([NACK_INCORRECT_PATTERN]))

        if length > MAX_PAYLOAD:
            return build(GENERIC_NACK, bytes([NACK_MESSAGE_TOO_LARGE]))
        # A header that claims more bytes than arrived is the classic way
        # to walk a parser off the end of its buffer. The length is
        # checked against what actually arrived, never trusted alone.
        if len(message) < HEADER_LEN + length:
            return build(GENERIC_NACK, bytes([NACK_INVALID_LENGTH]))

        payload = message[HEADER_LEN:HEADER_LEN + length]

        if payload_type == VEHICLE_IDENT_REQ:
            # Answered before routing activation on purpose: this is how a
            # tester discovers what it is plugged into.
            return build(VEHICLE_IDENT_RESP,
                         VIN + struct.pack(">H", ENTITY_ADDRESS)
                         + bytes([0xAA]) * 6      # EID, normally the MAC
                         + bytes([0xBB]) * 6      # GID, the group id
                         + bytes([0x00]))         # no further action needed

        if payload_type == ROUTING_ACTIVATION_REQ:
            if length < 7:
                return build(GENERIC_NACK, bytes([NACK_INVALID_LENGTH]))
            tester = struct.unpack(">H", payload[:2])[0]
            # Address 0x0000 is not a tester. Accepting whatever asks is
            # how a gateway ends up talking to anything on the network.
            if tester == 0x0000:
                code = ROUTING_UNKNOWN_SOURCE
            else:
                code = ROUTING_SUCCESS
                self.routing_active = True
                self.active_tester = tester
            return build(ROUTING_ACTIVATION_RESP,
                         struct.pack(">HHB", tester, ENTITY_ADDRESS, code) + bytes(4))

        if payload_type == DIAG_MESSAGE:
            if length < 5:
                return build(GENERIC_NACK, bytes([NACK_INVALID_LENGTH]))
            source, target = struct.unpack(">HH", payload[:4])

            # The check the whole state machine exists for. Without it,
            # anyone who can reach port 13400 can talk UDS to the car.
            if not self.routing_active or source != self.active_tester or target != ENTITY_ADDRESS:
                return build(DIAG_NACK,
                             struct.pack(">HHB", target, source, DIAG_NACK_UNKNOWN_TARGET))

            # The gateway understands none of the UDS it carries, which is
            # the point: a new service must not require editing this file.
            uds_response = self.uds_handler(payload[4:]) if self.uds_handler else b""
            if not uds_response:
                return None
            return build(DIAG_MESSAGE,
                         struct.pack(">HH", ENTITY_ADDRESS, source) + uds_response)

        return build(GENERIC_NACK, bytes([NACK_UNKNOWN_PAYLOAD]))


def _read_exactly(sock: socket.socket, count: int) -> bytes:
    """TCP is a stream, not a message queue. One recv can return half a
    message, or three of them stuck together. Assuming otherwise works on
    a fast local link and then fails in the workshop."""
    chunks = []
    while count:
        chunk = sock.recv(count)
        if not chunk:
            raise ConnectionError("peer closed the connection")
        chunks.append(chunk)
        count -= len(chunk)
    return b"".join(chunks)


def recv_message(sock: socket.socket) -> bytes:
    header = _read_exactly(sock, HEADER_LEN)
    _, length = parse_header(header)
    return header + _read_exactly(sock, length)


def serve(gateway: Gateway, port: int = TCP_PORT, host: str = "127.0.0.1",
          ready: threading.Event | None = None) -> None:
    """Serves one tester connection, then returns. Loopback only."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(1)
        if ready is not None:
            ready.port = listener.getsockname()[1]
            ready.set()

        conn, _ = listener.accept()
        with conn:
            gateway.reset_session()
            while True:
                try:
                    message = recv_message(conn)
                except (ConnectionError, OSError, ValueError):
                    break
                response = gateway.handle(message)
                if response:
                    conn.sendall(response)


def start_background(gateway: Gateway) -> int:
    """Starts a gateway on a free port and returns that port."""
    ready = threading.Event()
    threading.Thread(target=serve, args=(gateway, 0),
                     kwargs={"ready": ready}, daemon=True).start()
    if not ready.wait(5):
        raise TimeoutError("gateway did not come up")
    return ready.port


class DoipClient:
    """The tester side. Works against this gateway or the C one."""

    def __init__(self, host: str = "127.0.0.1", port: int = TCP_PORT,
                 address: int = TESTER_ADDRESS) -> None:
        self.address = address
        self.sock = socket.create_connection((host, port), timeout=5)

    def close(self) -> None:
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def request(self, payload_type: int, payload: bytes = b"") -> bytes:
        self.sock.sendall(build(payload_type, payload))
        return recv_message(self.sock)

    def identify(self) -> bytes:
        return self.request(VEHICLE_IDENT_REQ)[HEADER_LEN:]

    def activate_routing(self) -> int:
        response = self.request(ROUTING_ACTIVATION_REQ,
                                struct.pack(">HB", self.address, 0x00) + bytes(4))
        return response[HEADER_LEN + 4]

    def send_uds(self, uds: bytes, target: int = ENTITY_ADDRESS) -> bytes:
        response = self.request(DIAG_MESSAGE,
                                struct.pack(">HH", self.address, target) + uds)
        payload_type, _ = parse_header(response)
        if payload_type != DIAG_MESSAGE:
            raise PermissionError(f"gateway refused, payload type 0x{payload_type:04X}")
        return response[HEADER_LEN + 4:]


def uds_ecu_handler(ecu=None, wire: list | None = None) -> UdsHandler:
    """The gateway's real job: diagnostics in over Ethernet, out onto CAN.

    Each UDS request is segmented by ISO-TP and delivered to the simulated
    ECU from ``busbench.uds``, exactly as it would go out on the vehicle's
    CAN side. Pass ``wire`` to record every CAN frame as ("tx"|"rx", bytes).
    """
    from busbench.uds import isotp
    from busbench.uds.ecu import EcuSim

    ecu = ecu or EcuSim()

    def send(frame: bytes) -> None:
        if wire is not None:
            wire.append(("tx", frame))
        ecu.client_send(frame)

    def recv() -> bytes | None:
        frame = ecu.client_recv()
        if frame is not None and wire is not None:
            wire.append(("rx", frame))
        return frame

    def handle(uds: bytes) -> bytes:
        isotp.send_blocking(uds, send, recv)
        while True:
            response = isotp.recv_blocking(send, recv)
            # ponytail: the gateway absorbs 0x78 responsePending and returns
            # the final answer; a production gateway forwards each one.
            if not (len(response) >= 3 and response[0] == 0x7F and response[2] == 0x78):
                return response

    handle.ecu = ecu
    return handle


def tiny_ecu(uds: bytes) -> bytes:
    """Stands in for the ECUs that would sit on the CAN side."""
    if uds[:1] == b"\x10" and len(uds) >= 2:
        return bytes([0x50, uds[1]])
    if uds[:3] == b"\x22\xf1\x90":
        return b"\x62\xf1\x90" + VIN
    return bytes([0x7F, uds[0], 0x11])          # serviceNotSupported


def demo() -> None:
    port = start_background(Gateway(tiny_ecu))

    with DoipClient(port=port) as tester:
        print("vehicle identification:", tester.identify()[:17].decode())

        try:
            tester.send_uds(b"\x22\xf1\x90")
        except PermissionError as exc:
            print("before activation     :", exc)

        print("routing activation    : code 0x%02X" % tester.activate_routing())
        print("read VIN over TCP     :", tester.send_uds(b"\x22\xf1\x90")[3:].decode())


if __name__ == "__main__":
    demo()
