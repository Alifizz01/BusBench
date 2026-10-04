"""UDS diagnostic client, the scan-tool side of ISO 14229.

Every service is the same three steps: build a request, hand it to
ISO-TP, then work out whether what came back is an answer, a refusal, or
the ECU asking for more time.

The C version returns a ``UdsResult_t``. Here a refusal raises
``NegativeResponse`` instead, which is what the Python ecosystem expects
and means a caller cannot ignore it by forgetting to check a return code.

    python -m busbench.uds.client
"""

from __future__ import annotations

from . import isotp
from .ecu import EcuSim, key_from_seed

PENDING_LIMIT = 16       # an ECU may stall, but not forever

NRC_NAMES = {
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x78: "responsePending",
    0x7F: "serviceNotSupportedInActiveSession",
}


class NegativeResponse(Exception):
    def __init__(self, sid: int, nrc: int) -> None:
        self.sid, self.nrc = sid, nrc
        super().__init__(f"service 0x{sid:02X} refused: "
                         f"0x{nrc:02X} {NRC_NAMES.get(nrc, 'unknown')}")


class UdsClient:
    def __init__(self, send, recv) -> None:
        self._send, self._recv = send, recv

    def _transact(self, request: bytes) -> bytes:
        isotp.send_blocking(request, self._send, self._recv)

        for _ in range(PENDING_LIMIT):
            response = isotp.recv_blocking(self._send, self._recv)

            if len(response) >= 3 and response[0] == 0x7F:
                # 0x78 is not a failure, it means "still working, keep
                # waiting". Treating it as an error is the classic
                # mistake that makes a tester look broken against a slow
                # ECU.
                if response[2] == 0x78:
                    continue
                raise NegativeResponse(response[1], response[2])

            # A positive response is always the request SID plus 0x40.
            if response[0] != (request[0] + 0x40) & 0xFF:
                raise isotp.IsoTpError(f"unexpected response SID 0x{response[0]:02X}")
            return response

        raise TimeoutError("ECU kept asking for more time")

    def start_session(self, session_type: int) -> bytes:
        return self._transact(bytes([0x10, session_type]))

    def read_data_by_identifier(self, did: int) -> bytes:
        request = bytes([0x22, did >> 8, did & 0xFF])
        response = self._transact(request)
        # Guard against an ECU answering with a different identifier.
        if response[1:3] != request[1:3]:
            raise isotp.IsoTpError("ECU answered with the wrong identifier")
        return response[3:]

    def request_seed(self, level: int = 0x01) -> bytes:
        return self._transact(bytes([0x27, level]))[2:]

    def security_access(self, level: int, key: bytes) -> None:
        self._transact(bytes([0x27, level]) + key)

    def write_data_by_identifier(self, did: int, data: bytes) -> None:
        self._transact(bytes([0x2E, did >> 8, did & 0xFF]) + data)

    def unlock(self, level: int = 0x01) -> int:
        """Both halves of the handshake: seed out, key back in at level+1."""
        seed = int.from_bytes(self.request_seed(level), "big")
        key = key_from_seed(seed)
        self.security_access(level + 1, key.to_bytes(4, "big"))
        return seed


def demo() -> None:
    ecu = EcuSim()
    client = UdsClient(ecu.client_send, ecu.client_recv)

    client.start_session(0x01)
    print("VIN           ", client.read_data_by_identifier(0xF190).decode())
    print("SW version    ", client.read_data_by_identifier(0xF195).decode())
    rpm = client.read_data_by_identifier(0x0110)
    print("Engine speed  ", int.from_bytes(rpm, "big"), "raw (after a responsePending)")

    try:
        client.read_data_by_identifier(0xDEAD)
    except NegativeResponse as exc:
        print("unknown DID   ", exc)

    client.start_session(0x03)
    try:
        client.write_data_by_identifier(0xF199, b"\x12\x34")
    except NegativeResponse as exc:
        print("write locked  ", exc)

    seed = client.unlock()
    print(f"unlocked       seed 0x{seed:08X} -> key 0x{key_from_seed(seed):08X}")
    client.write_data_by_identifier(0xF199, b"\x12\x34")
    print("write ok      ", ecu.written)


if __name__ == "__main__":
    demo()
