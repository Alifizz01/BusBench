"""A stand-in ECU so the client has something to talk to.

It answers a handful of real UDS services and, importantly, refuses
things the way a real ECU refuses them: wrong session, still locked,
unknown identifier.
"""

from __future__ import annotations

from collections import deque

from isotp import IsoTpRx, IsoTpTx

# Negative response codes, ISO 14229 table.
NRC_SERVICE_NOT_SUPPORTED = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED = 0x12
NRC_REQUEST_OUT_OF_RANGE = 0x31
NRC_SECURITY_ACCESS_DENIED = 0x33
NRC_INVALID_KEY = 0x35
NRC_RESPONSE_PENDING = 0x78
NRC_WRONG_SESSION = 0x7F

VIN = b"WVWZZZ1JZ3W386752"


def key_from_seed(seed: int) -> int:
    """Stand-in for the manufacturer's secret seed/key algorithm.

    A real one lives in an HSM and is not in the repository, but the
    shape of the handshake is identical.
    """
    return ((seed ^ 0x5A5A5A5A) + 0x11223344) & 0xFFFFFFFF


class EcuSim:
    def __init__(self) -> None:
        self.queue: deque[bytes] = deque(maxlen=64)
        self.rx = IsoTpRx()
        self.tx = IsoTpTx()
        self.session = 0x01           # 0x01 default, 0x03 extended
        self.unlocked = False
        self.seed = 0
        self._rng = 0xACE1
        self.written: dict[int, bytes] = {}

    # The two ends of the simulated CAN link.
    def client_send(self, frame: bytes) -> None:
        if not frame:
            return
        if (frame[0] & 0xF0) == 0x30:            # flow control for a reply in progress
            self.tx.on_flow_control(self.queue.append)
            return
        request = self.rx.feed(frame, self.queue.append)
        if request is not None:
            self._handle(request)

    def client_recv(self) -> bytes | None:
        return self.queue.popleft() if self.queue else None

    def _respond(self, payload: bytes) -> None:
        self.tx.start(payload, self.queue.append)

    def _negative(self, sid: int, nrc: int) -> None:
        self._respond(bytes([0x7F, sid, nrc]))

    def _handle(self, req: bytes) -> None:
        sid = req[0]

        if sid == 0x10:                          # DiagnosticSessionControl
            if len(req) < 2 or req[1] not in (0x01, 0x03):
                return self._negative(sid, NRC_SUBFUNCTION_NOT_SUPPORTED)
            self.session = req[1]
            if self.session == 0x01:
                self.unlocked = False            # dropping session relocks
            # echo the session plus the P2 timing the tester must honour
            return self._respond(bytes([0x50, req[1], 0x00, 0x32, 0x01, 0xF4]))

        if sid == 0x22:                          # ReadDataByIdentifier
            if len(req) < 3:
                return self._negative(sid, NRC_REQUEST_OUT_OF_RANGE)
            did = (req[1] << 8) | req[2]
            head = bytes([0x62, req[1], req[2]])

            if did == 0xF190:                    # VIN, 17 bytes, forces segmentation
                return self._respond(head + VIN)
            if did == 0xF195:
                return self._respond(head + b"1.4.2")
            if did == 0x0110:
                # Real ECUs stall on a live measurement, so this one does
                # too: the tester has to keep waiting through 0x78.
                self._respond(bytes([0x7F, 0x22, NRC_RESPONSE_PENDING]))
                return self._respond(head + bytes([0x0F, 0xA0]))
            return self._negative(sid, NRC_REQUEST_OUT_OF_RANGE)

        if sid == 0x27:                          # SecurityAccess
            if len(req) < 2:
                return self._negative(sid, NRC_SUBFUNCTION_NOT_SUPPORTED)
            if self.session != 0x03:
                return self._negative(sid, NRC_WRONG_SESSION)

            if req[1] == 0x01:                   # requestSeed
                self._rng = (self._rng * 1103515245 + 12345) & 0xFFFFFFFF
                self.seed = self._rng
                return self._respond(bytes([0x67, 0x01]) + self.seed.to_bytes(4, "big"))

            if req[1] == 0x02:                   # sendKey
                if len(req) < 6 or int.from_bytes(req[2:6], "big") != key_from_seed(self.seed):
                    return self._negative(sid, NRC_INVALID_KEY)
                self.unlocked = True
                return self._respond(bytes([0x67, 0x02]))

            return self._negative(sid, NRC_SUBFUNCTION_NOT_SUPPORTED)

        if sid == 0x2E:                          # WriteDataByIdentifier
            if not self.unlocked:
                return self._negative(sid, NRC_SECURITY_ACCESS_DENIED)
            if len(req) < 4:
                return self._negative(sid, NRC_REQUEST_OUT_OF_RANGE)
            self.written[(req[1] << 8) | req[2]] = bytes(req[3:])
            return self._respond(bytes([0x6E, req[1], req[2]]))

        return self._negative(sid, NRC_SERVICE_NOT_SUPPORTED)
