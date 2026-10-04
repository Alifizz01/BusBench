"""Everything the Studio can do, as plain functions: dict in, dict out.

server.py exposes each entry of ROUTES as POST /api/<name>. Nothing here
re-implements a protocol; it drives the modules and reports what they did.
Stateful modules (a UDS session, a 1553 bus, a recorder store) keep one
live instance per Studio session in STATE.
"""
from __future__ import annotations

import os
import struct
import subprocess
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path

import busbench
from busbench.modules import MODULES

PKG = Path(__file__).resolve().parent
STATE: dict = {}
LOCK = threading.Lock()


def _hex(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def _unhex(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", "").replace("0x", "").replace(",", ""))


def _num(v) -> int:
    return int(v, 0) if isinstance(v, str) else int(v)


def _read(module: str, *parts: str) -> str:
    return (PKG / module / "data").joinpath(*parts).read_text(encoding="utf-8")


# ------------------------------------------------------------------ overview
def modules(_=None):
    return {"version": busbench.__version__,
            "modules": [asdict(m) for m in MODULES],
            "last_test": STATE.get("test", {}).get("report")}


def test_start(body):
    """Run the C + Python suites in the background; poll test_status."""
    from busbench.runner import run_all
    if STATE.get("test", {}).get("running"):
        return test_status()
    job = STATE["test"] = {"running": True, "done": [], "report": None, "compiler": None}

    def work():
        try:
            rep = run_all(body.get("modules") or None, bool(body.get("python_only")),
                          on_result=lambda r: job["done"].append(asdict(r)))
            job["report"], job["compiler"] = rep.to_dict(), rep.compiler
        except Exception as exc:          # surfaced to the GUI, never swallowed
            job["error"] = f"{type(exc).__name__}: {exc}"
        job["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return test_status()


def test_status(_=None):
    job = STATE.get("test") or {"running": False, "done": [], "report": None}
    return {k: v for k, v in job.items()}


# ------------------------------------------------------------------ CAN
def can_sample(_=None):
    return {"dbc": _read("can", "example.dbc"), "log": _read("can", "example.log")}


def can_decode(body):
    from busbench.can.decoder import decode, load_dbc, read_log, signal_bits
    with tempfile.TemporaryDirectory() as d:
        Path(d, "x.dbc").write_text(body["dbc"], encoding="utf-8")
        Path(d, "x.log").write_text(body["log"], encoding="utf-8")
        sigs, frames = load_dbc(Path(d, "x.dbc")), read_log(Path(d, "x.log"))
    out_frames = []
    for f in frames:
        values = {s.name: decode(s, f) for s in sigs if s.can_id == f.can_id}
        out_frames.append({"t": f.timestamp_us / 1e6, "id": f.can_id, "data": _hex(f.data),
                           "values": {k: v for k, v in values.items() if v is not None}})
    return {"signals": [{**asdict(s), "bits": signal_bits(s)} for s in sigs], "frames": out_frames}


# ------------------------------------------------------------------ UDS
def _uds():
    if "uds" not in STATE:
        uds_reset()
    return STATE["uds"]


def uds_reset(_=None):
    from busbench.uds.client import UdsClient
    from busbench.uds.ecu import EcuSim
    ecu, wire = EcuSim(), []

    def send(frame):
        wire.append(("tester", frame))
        ecu.client_send(frame)

    def recv():
        frame = ecu.client_recv()
        if frame is not None:
            wire.append(("ecu", frame))
        return frame
    STATE["uds"] = {"ecu": ecu, "client": UdsClient(send, recv), "wire": wire}
    return {"ecu": _ecu_state(ecu)}


def _ecu_state(ecu):
    return {"session": "extended" if ecu.session == 0x03 else "default", "unlocked": ecu.unlocked,
            "written": {f"0x{k:04X}": _hex(v) for k, v in ecu.written.items()}}


def _isotp_kind(frame: bytes) -> str:
    return {0x00: "SF", 0x10: "FF", 0x20: "CF", 0x30: "FC"}.get(frame[0] & 0xF0, "?")


def uds_request(body):
    from busbench.uds import isotp
    from busbench.uds.client import NRC_NAMES, NegativeResponse
    from busbench.uds.ecu import key_from_seed
    u = _uds()
    client, wire = u["client"], u["wire"]
    wire.clear()
    action = body.get("action", "raw")
    out = {"action": action}
    try:
        if action == "unlock":
            seed = client.unlock(int(body.get("level", 1)))
            out["note"] = f"seed 0x{seed:08X} -> key 0x{key_from_seed(seed):08X}"
        else:
            request = _unhex(body["request"])
            out["request"] = _hex(request)
            response = client._transact(request)
            out["response"] = _hex(response)
            if response[0] == 0x62 and len(response) > 3:
                text = response[3:]
                out["note"] = (text.decode("ascii") if all(32 <= c < 127 for c in text)
                               else f"raw value {int.from_bytes(text, 'big')}")
        out["ok"] = True
    except NegativeResponse as exc:
        out.update(ok=False, nrc=f"0x{exc.nrc:02X}", error=str(exc), nrc_name=NRC_NAMES.get(exc.nrc, "unknown"))
    except (isotp.IsoTpError, TimeoutError, ValueError, KeyError) as exc:
        out.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    out["frames"] = [{"from": who, "kind": _isotp_kind(f), "bytes": _hex(f)} for who, f in wire]
    out["pending"] = sum(1 for who, f in wire if who == "ecu" and f[1:4] == b"\x7F\x22\x78")
    out["ecu"] = _ecu_state(u["ecu"])
    return out


# ------------------------------------------------------------------ AUTOSAR
def autosar_reset(_=None):
    from busbench.autosar.ecu import build_ecu
    rte, bsw, swc = build_ecu()
    STATE["autosar"] = {"rte": rte, "bsw": bsw, "swc": swc}
    return {"t": 0}


def autosar_run(body):
    """Advance the ECU by `ms`, sampling every RTE signal each 10 ms tick.
    mode 'traffic' runs the BSW traffic generator, 'manual' injects the
    given speed/brake as CAN frames, 'dead' sends nothing at all."""
    from busbench.autosar.bsw import CAN_ID_CHASSIS
    from busbench.autosar.rte import Signal
    if "autosar" not in STATE:
        autosar_reset()
    a = STATE["autosar"]
    rte, bsw = a["rte"], a["bsw"]
    mode = body.get("mode", "traffic")
    bsw.traffic_enabled = mode == "traffic"
    samples = []
    for _ in range(max(1, int(body.get("ms", 1000)) // 10)):
        if mode == "manual":
            speed = int(float(body.get("speed", 80)) * 100)
            bsw.inject_can_frame(CAN_ID_CHASSIS, speed.to_bytes(2, "big") + bytes([1 if body.get("brake") else 0]))
        rte.start(10)
        samples.append({"t": rte.now_ms, "speed": rte.read(Signal.VEHICLE_SPEED),
                        "rpm": rte.read(Signal.ENGINE_RPM), "brake": rte.read(Signal.BRAKE_PRESSED),
                        "lamp": int(bsw.lamp_on), "fresh": rte.is_fresh(Signal.VEHICLE_SPEED, 100)})
    return {"samples": samples}


# ------------------------------------------------------------------ ISO 26262
def safety_watchdog(body):
    """Replay kick times against a windowed watchdog; report every event."""
    from busbench.safety.watchdog import WindowedWatchdog
    wd = WindowedWatchdog(int(body["open"]), int(body["close"]))
    wd.reset(0)
    events, kicks = [], sorted(int(k) for k in body.get("kicks", []))
    windows = [{"start": 0}]                 # every cycle start, so the GUI can draw each window
    for t in kicks:
        if not wd.poll(t):
            events.append({"t": wd.cycle_start + wd.close_ms, "kind": "expired",
                           "detail": "no kick before the window closed"})
            wd.reset(t)
            windows.append({"start": t})
            continue
        start = wd.cycle_start
        ok = wd.kick(t)
        kind = "ok" if ok else ("early" if t - start < wd.open_ms else "late")
        events.append({"t": t, "kind": kind, "since": t - start})
        if not ok:
            wd.reset(t)              # the fault is latched, monitoring restarts
        if wd.cycle_start != windows[-1]["start"]:
            windows.append({"start": wd.cycle_start})
    end = int(body.get("until", (kicks[-1] if kicks else 0) + wd.close_ms + 5))
    if not wd.poll(end):
        events.append({"t": wd.cycle_start + wd.close_ms, "kind": "expired",
                       "detail": "task stopped kicking"})
    return {"events": events, "until": end, "windows": windows}


def safety_plausibility(body):
    from busbench.safety.watchdog import plausibility_check
    ok = plausibility_check(float(body["prev"]), float(body["new"]), float(body["dt"]), float(body["max_rate"]))
    dt = float(body["dt"])
    rate = abs(float(body["new"]) - float(body["prev"])) / dt if dt > 0 else None
    return {"plausible": ok, "rate": rate}


def safety_faults(body):
    """Replay a list of report/heal operations, returning the state after each."""
    from busbench.safety.watchdog import FAULT_DEBOUNCE_COUNT, FaultMonitor
    fm, steps = FaultMonitor(), []
    for op in body.get("ops", []):
        fid = _num(op["id"])
        if op.get("op") == "heal":
            fm.heal(fid)
        else:
            fm.report(fid, int(op.get("severity", 1)))
        steps.append({"op": op.get("op", "report"), "id": f"0x{fid:X}", "state": fm.state.name,
                      "faults": {f"0x{k:X}": {"severity": f.severity, "count": f.count}
                                 for k, f in fm._faults.items()}})
    return {"steps": steps, "debounce": FAULT_DEBOUNCE_COUNT}


# ------------------------------------------------------------------ DoIP
def _parse_doip(frame: bytes) -> dict:
    from busbench.doip import gateway as g
    names = {g.GENERIC_NACK: "generic NACK", g.VEHICLE_IDENT_REQ: "vehicle identification request",
             g.VEHICLE_IDENT_RESP: "vehicle announcement", g.ROUTING_ACTIVATION_REQ: "routing activation request",
             g.ROUTING_ACTIVATION_RESP: "routing activation response", g.DIAG_MESSAGE: "diagnostic message",
             g.DIAG_ACK: "diagnostic ACK", g.DIAG_NACK: "diagnostic NACK"}
    version, inverse, ptype, length = struct.unpack(">BBHI", frame[:8])
    return {"hex": _hex(frame), "version": version, "inverse": inverse, "type": f"0x{ptype:04X}",
            "type_name": names.get(ptype, "unknown"), "length": length, "payload": _hex(frame[8:])}


def doip_start(body):
    """Start a gateway in the background and connect a tester to it.
    impl 'python' routes diagnostics to the UDS ECU over ISO-TP (and shows
    the CAN frames); impl 'c' builds and runs the C gateway."""
    from busbench.doip.gateway import TCP_PORT, DoipClient, Gateway, start_background, uds_ecu_handler
    doip_stop()
    impl = body.get("impl", "python")
    d = STATE["doip"] = {"impl": impl, "wire": []}
    if impl == "c":
        from busbench.runner import build_doip_server, connect_retry, find_compiler
        cc = find_compiler()
        if cc is None:
            raise RuntimeError("no C compiler found - install gcc/clang or Visual Studio C++ tools")
        exe, log = build_doip_server(cc)
        if exe is None:
            raise RuntimeError(f"C gateway did not build: {log[-400:]}")
        d["proc"] = subprocess.Popen([str(exe)], cwd=exe.parent, env=cc.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        d["client"] = connect_retry(lambda: DoipClient(port=TCP_PORT))
        d["port"], d["compiler"] = TCP_PORT, cc.label
    else:
        port = start_background(Gateway(uds_ecu_handler(wire=d["wire"])))
        d["client"], d["port"] = DoipClient(port=port), port
    return {"impl": impl, "port": d["port"], "compiler": d.get("compiler")}


def doip_stop(_=None):
    d = STATE.pop("doip", None)
    if d:
        try:
            d["client"].close()
        except Exception:
            pass
        if d.get("proc"):
            d["proc"].terminate()
    return {"stopped": bool(d)}


def doip_send(body):
    from busbench.doip import gateway as g
    d = STATE.get("doip")
    if not d:
        raise RuntimeError("start a gateway first")
    c, action = d["client"], body.get("action")
    d["wire"].clear()
    if action == "identify":
        payload_type, payload = g.VEHICLE_IDENT_REQ, b""
    elif action == "activate":
        payload_type, payload = g.ROUTING_ACTIVATION_REQ, struct.pack(">HB", _num(body.get("tester", c.address)), 0) + bytes(4)
    else:
        payload_type = g.DIAG_MESSAGE
        payload = struct.pack(">HH", _num(body.get("tester", c.address)), _num(body.get("target", g.ENTITY_ADDRESS))) + _unhex(body["uds"])
    request = g.build(payload_type, payload)
    c.sock.sendall(request)
    response = g.recv_message(c.sock)
    return {"request": _parse_doip(request), "response": _parse_doip(response),
            "can": [{"from": "gateway" if who == "tx" else "ecu", "kind": _isotp_kind(f), "bytes": _hex(f)}
                    for who, f in d["wire"]]}


# ------------------------------------------------------------------ ARINC 429
def arinc429_sample(_=None):
    return {"labels": _read("arinc429", "labels.csv"), "capture": _read("arinc429", "capture.txt")}


def _word(word: int, dictionary) -> dict:
    from busbench.arinc429 import analyzer as a
    res = a.analyze(word, dictionary)
    out = {"hex": f"{word:08X}", "bits": f"{word:032b}", "label": f"{a.get_label(word):03o}",
           "sdi": a.get_sdi(word), "ssm": a.get_ssm(word), "ssm_name": a.SSM_NAMES[a.get_ssm(word)],
           "parity_ok": a.check_parity(word), "usable": a.is_usable(word)}
    if res:
        entry, value = res
        out.update(name=entry.name, unit=entry.unit, value=value, data_bits=entry.data_bits)
    return out


def _dict429(text: str):
    from busbench.arinc429.analyzer import load_dictionary
    with tempfile.TemporaryDirectory() as d:
        Path(d, "l.csv").write_text(text, encoding="utf-8")
        return load_dictionary(Path(d, "l.csv"))


def arinc429_analyze(body):
    dictionary = _dict429(body["labels"])
    words = []
    for line in body["capture"].splitlines():
        line = line.split("#")[0].strip()
        if line:
            words.append(_word(int(line, 16), dictionary))
    return {"words": words}


def arinc429_build(body):
    from busbench.arinc429.analyzer import build_word
    dictionary = _dict429(body["labels"])
    label = int(str(body["label"]), 8)
    entry = dictionary.get(label)
    bits = int(body.get("data_bits") or (entry.data_bits if entry else 19))
    scale = float(body.get("scale") or (entry.lsb_scale if entry else 1.0))
    raw = round(float(body["value"]) / scale)
    word = build_word(label, int(body.get("sdi", 0)), raw & ((1 << bits) - 1), int(body.get("ssm", 3)), bits)
    return _word(word, dictionary)


# ------------------------------------------------------------------ MIL-STD-1553
def _bc():
    if "mil1553" not in STATE:
        mil1553_reset()
    return STATE["mil1553"]


def mil1553_reset(_=None):
    from busbench.mil1553.bus import BusController
    bc = BusController()
    for addr, data in ((3, [0x1111, 0x2222, 0x3333, 0x4444]), (5, [0xAAAA, 0xBBBB])):
        bc.connect(addr).data[1] = data
    STATE["mil1553"] = bc
    return mil1553_state()


def mil1553_state(_=None):
    bc = _bc()
    return {"rts": [{"address": a, "connected": rt.connected, "busy": rt.busy,
                     "subsystem_fault": rt.subsystem_fault, "broadcasts": rt.broadcasts_received,
                     "data": {str(sa): [f"0x{w:04X}" for w in words] for sa, words in rt.data.items()}}
                    for a, rt in sorted(bc.rts.items())],
            "transactions": bc.transactions, "retries": bc.retries, "failures": bc.failures}


def mil1553_rt(body):
    bc, addr = _bc(), int(body["address"])
    if body.get("remove"):
        bc.rts.pop(addr, None)
    else:
        rt = bc.rts.get(addr) or bc.connect(addr)
        for k in ("connected", "busy", "subsystem_fault"):
            if k in body:
                setattr(rt, k, bool(body[k]))
    return mil1553_state()


def _cmd_info(cmd) -> dict:
    raw = cmd.encode()
    return {"hex": f"{raw:04X}", "bits": f"{raw:016b}", "rt": cmd.rt_address, "tr": cmd.tr,
            "sa": cmd.subaddress, "wc": cmd.word_count, "mode_code": cmd.is_mode_code}


def mil1553_transact(body):
    from busbench.mil1553.bus import CommandWord, Timeout, TransactionError
    bc = _bc()
    cmd = CommandWord(int(body["rt"]), int(body["tr"]), int(body["sa"]), int(body["wc"]))
    data = [_num(w) for w in body.get("data", [])]
    out = {"command": _cmd_info(cmd)}
    try:
        words, status = bc.transact(cmd, data)
        out.update(ok=True, words=[f"0x{w:04X}" for w in words],
                   status={"rt": status.rt_address, "flags": f"{status.flags:011b}"},
                   broadcast=cmd.rt_address == 31)
    except Timeout as exc:
        out.update(ok=False, kind="timeout", error=str(exc))
    except TransactionError as exc:
        out.update(ok=False, kind="error", error=str(exc))
    out["bus"] = mil1553_state()
    return out


def mil1553_schedule(body):
    from busbench.mil1553.bus import CommandWord
    bc = _bc()
    cmds = [CommandWord(int(c["rt"]), int(c["tr"]), int(c["sa"]), int(c["wc"])) for c in body["commands"]]
    log = bc.run_schedule(cmds)
    return {"log": [{**_cmd_info(e["command"]), "attempts": e["attempts"], "ok": e["ok"]} for e in log],
            "bus": mil1553_state()}


# ------------------------------------------------------------------ ARINC 653
def arinc653_run(body):
    """Build a schedule from the GUI's table and run it, recording exactly
    when each partition started and stopped. Behaviours:
      nominal  - works `work` ms then yields
      greedy   - keeps asking for time until it is cut off
      nosy     - also writes into its neighbour's memory region
      hung     - never yields (an infinite loop, cut off at its boundary)"""
    from busbench.arinc653.scheduler import ConfigError, Partition, Scheduler
    rows = body["partitions"]
    segments: list[dict] = []
    sched: Scheduler

    def entry(i, row):
        def run():
            start = sched.now_ms
            behaviour, work = row.get("behaviour", "nominal"), int(row.get("work", 1))
            if behaviour == "nosy":
                victim = (i + 1) % len(rows)
                sched.write(victim, 0, 0xBAD)
            ok = True
            if behaviour in ("greedy", "hung"):
                while sched.work(1):
                    pass
                ok = False
            else:
                ok = sched.work(work)
            sched.write(i, 0, sched.frames_run)
            segments.append({"frame": sched.frames_run, "partition": row["name"], "start": start,
                             "end": sched.now_ms, "cut_off": not ok})
        return run
    try:
        parts = [Partition(r["name"], int(r["offset"]), int(r["duration"]), None, i) for i, r in enumerate(rows)]
        sched = Scheduler(parts, int(body["major_frame"]))
    except (ConfigError, KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    for i, (p, r) in enumerate(zip(parts, rows)):
        p.entry_point = entry(i, r)
    sched.run(int(body.get("frames", 3)))
    return {"ok": True, "segments": segments, "major_frame": sched.major_frame_ms,
            "health": {k: asdict(v) for k, v in sched.health.items()}}


# ------------------------------------------------------------------ DO-178C
def traceability_sample(_=None):
    src = PKG / "traceability" / "data" / "src"
    return {"requirements": _read("traceability", "requirements.csv"),
            "results": _read("traceability", "results.xml"),
            "sources": {f.name: f.read_text(encoding="utf-8") for f in sorted(src.iterdir())}}


def traceability_analyze(body):
    from busbench.traceability import trace
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "r.csv").write_text(body["requirements"], encoding="utf-8")
        (root / "r.xml").write_text(body["results"], encoding="utf-8")
        (root / "src").mkdir()
        for name, text in (body.get("sources") or {}).items():
            (root / "src" / Path(name).name).write_text(text, encoding="utf-8")
        reqs = trace.load_requirements(root / "r.csv")
        results = trace.load_results(root / "r.xml")
        links = trace.scan_source_tree(root / "src")
        summary = trace.analyse(reqs, results, links)
        trace.write_report(reqs, summary, root / "report.md")
        report = (root / "report.md").read_text(encoding="utf-8")
    return {"requirements": [asdict(r) for r in reqs],
            "tests": [asdict(t) for t in results.values()],
            "links": [asdict(ln) for ln in links],
            "summary": {**asdict(summary), "problems": summary.problems,
                        "bad_annotations": [asdict(b) for b in summary.bad_annotations]},
            "report": report}


# ------------------------------------------------------------------ FDR
def fdr_reset(body=None):
    from busbench.fdr.recorder import FdrLogger
    old = STATE.pop("fdr", None)
    if old:
        old["logger"].close()
    path = Path(tempfile.gettempdir()) / f"busbench_studio_{os.getpid()}.bin"
    path.unlink(missing_ok=True)
    tick = {"t": 0}

    def clock():
        tick["t"] += 1000
        return tick["t"]
    capacity = int((body or {}).get("capacity", 16))
    STATE["fdr"] = {"logger": FdrLogger(path, capacity, clock=clock), "path": path, "capacity": capacity}
    return fdr_state()


def _fdr():
    if "fdr" not in STATE:
        fdr_reset()
    return STATE["fdr"]


def fdr_state(_=None):
    from busbench.fdr.recorder import FRAME_BYTES, SOURCE_NAMES, Frame, replay
    f = _fdr()
    raw = f["path"].read_bytes()
    slots = []
    for i in range(f["capacity"]):
        chunk = raw[i * FRAME_BYTES:(i + 1) * FRAME_BYTES]
        frame = Frame.unpack(chunk) if any(chunk) else None
        state = "empty" if not any(chunk) else ("valid" if frame else "corrupt")
        slots.append({"slot": i, "state": state, "hex": _hex(chunk),
                      **({"t": frame.timestamp_us, "source": SOURCE_NAMES.get(frame.source, "?"),
                          "payload": _hex(frame.payload)} if frame else {})})
    frames, discarded = replay(f["path"])
    return {"capacity": f["capacity"], "next_slot": f["logger"].next_slot, "slots": slots,
            "replay": {"recovered": len(frames), "discarded": discarded,
                       "order": [fr.timestamp_us for fr in frames]}}


def fdr_append(body):
    from busbench.fdr.recorder import SOURCE_EVENT
    f = _fdr()
    for _ in range(int(body.get("count", 1))):
        f["logger"].append(int(body.get("source", SOURCE_EVENT)), _unhex(body.get("payload", "")) or b"\x01")
    return fdr_state()


def fdr_record_buses(_=None):
    """The integration: the CAN log from module can and the ARINC 429
    capture from module arinc429 go into the recorder."""
    from busbench.arinc429.analyzer import read_capture
    from busbench.can.decoder import read_log
    from busbench.fdr.recorder import record_buses
    n = record_buses(_fdr()["logger"], read_log(PKG / "can" / "data" / "example.log"),
                     read_capture(PKG / "arinc429" / "data" / "capture.txt"))
    return {**fdr_state(), "written": n}


def fdr_corrupt(body):
    from busbench.fdr.recorder import FRAME_BYTES
    f = _fdr()
    slot = int(body["slot"])
    offset = slot * FRAME_BYTES + 14                   # first payload byte (after magic, time, src, len)
    byte = f["path"].read_bytes()[offset]
    f["logger"].file.seek(offset)
    f["logger"].file.write(bytes([byte ^ 0xFF]))
    f["logger"].file.flush()
    return fdr_state()


ROUTES = {name: fn for name, fn in globals().items()
          if callable(fn) and not name.startswith("_") and fn.__module__ == __name__
          and name.split("_")[0] in {"modules", "test", *(m.id for m in MODULES)}}
