"""Cross-module and cross-language tests: the places where modules meet."""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from busbench import api
from busbench.arinc429.analyzer import read_capture
from busbench.can.decoder import read_log
from busbench.doip.gateway import DoipClient, Gateway, start_background, uds_ecu_handler
from busbench.fdr.recorder import SOURCE_ARINC, SOURCE_CAN, FdrLogger, record_buses, replay
from busbench.runner import find_compiler

PKG = Path(__file__).resolve().parent.parent / "busbench"


# @req REQ-502
def test_doip_routes_diagnostics_to_the_uds_ecu_over_isotp():
    wire = []
    port = start_background(Gateway(uds_ecu_handler(wire=wire)))
    with DoipClient(port=port) as tester:
        tester.activate_routing()
        vin = tester.send_uds(b"\x22\xf1\x90")
        assert vin[3:] == b"WVWZZZ1JZ3W386752"
        kinds = [f[0] & 0xF0 for _, f in wire]
        assert kinds == [0x00, 0x10, 0x30, 0x20, 0x20]     # SF out, FF back, FC, CF, CF
        rpm = tester.send_uds(b"\x22\x01\x10")              # the ECU stalls with 0x78 first
        assert rpm[0] == 0x62


# @req REQ-1003
def test_fdr_records_real_can_and_arinc_traffic(tmp_path):
    can = read_log(PKG / "can" / "data" / "example.log")
    words = read_capture(PKG / "arinc429" / "data" / "capture.txt")
    tick = iter(range(1, 10_000))
    with FdrLogger(tmp_path / "store.bin", 64, clock=lambda: next(tick)) as fdr:
        assert record_buses(fdr, can, words) == len(can) + len(words)
    frames, discarded = replay(tmp_path / "store.bin")
    assert discarded == 0
    assert [f.source for f in frames] == [SOURCE_CAN] * len(can) + [SOURCE_ARINC] * len(words)
    assert int.from_bytes(frames[0].payload[:4], "little") == can[0].can_id
    assert int.from_bytes(frames[-1].payload, "little") == words[-1]


# @req REQ-503
@pytest.mark.skipif(find_compiler() is None, reason="no C compiler")
def test_python_tester_drives_the_c_gateway_over_tcp():
    from busbench.runner import doip_interop
    status, log = doip_interop(find_compiler())
    assert status == "pass", log


# ------------------------------------------------------------- REST API
@pytest.fixture(scope="module")
def http():
    from busbench.server import make_server
    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(name, body=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(f"{base}/api/{name}", data=json.dumps(body or {}).encode(), headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
    yield post
    srv.shutdown()


# @req REQ-901
def test_every_module_is_reachable_through_the_api(http):
    assert http("can_decode", api.can_sample())[1]["frames"][0]["values"]["EngineSpeed"] == 2000.0
    assert http("uds_request", {"request": "22 F1 90"})[1]["note"] == "WVWZZZ1JZ3W386752"
    assert http("autosar_run", {"ms": 200, "mode": "dead"})[1]["samples"][-1]["lamp"] == 1
    assert http("safety_plausibility", {"prev": 0, "new": 500, "dt": 1, "max_rate": 100})[1]["plausible"] is False
    assert http("arinc429_analyze", api.arinc429_sample())[1]["words"][0]["name"] == "ALTITUDE"
    assert http("mil1553_transact", {"rt": 9, "tr": 1, "sa": 1, "wc": 4})[1]["kind"] == "timeout"
    sched = {"major_frame": 20, "partitions": [{"name": "A", "offset": 0, "duration": 10, "behaviour": "hung"}]}
    assert http("arinc653_run", sched)[1]["health"]["A"]["overruns"] == 3     # once per frame
    assert http("traceability_analyze", api.traceability_sample())[1]["summary"]["problems"] == 5
    assert http("fdr_record_buses")[1]["written"] == 10


# @req REQ-902
def test_api_refuses_cross_site_requests(http):
    assert http("modules", headers={"Host": "evil.example"})[0] == 403
    assert http("modules", headers={"Content-Type": "text/plain"})[0] == 415
    code, body = http("can_decode", {"dbc": "x"})
    assert code == 400 and "KeyError" in body["error"]
