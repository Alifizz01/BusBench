"""busbench command line.

    busbench test [MODULE ...] [--py] [-v]   build + run C and Python tests (exit 1 on failure)
    busbench test --sanitize                 C tests under AddressSanitizer + UBSan (gcc/clang)
    busbench trace --requirements R --results JUNIT --source DIR...   DO-178C traceability gate
    busbench demo MODULE                     run one module's demo
    busbench studio                          open the desktop GUI
    busbench serve [--port 8770]             REST API + Studio in a browser
"""
import argparse
import importlib
import sys
from pathlib import Path

from busbench.modules import BY_ID

DEMOS = {"can": "decoder:main", "uds": "client:demo", "autosar": "ecu:main", "safety": "watchdog:demo",
         "doip": "gateway:demo", "arinc429": "analyzer:main", "mil1553": "bus:demo",
         "arinc653": "scheduler:demo", "traceability": "trace:main", "fdr": "recorder:demo"}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["trace"]:                  # pass every option straight through
        from busbench.traceability.trace import main as trace_main
        return trace_main(argv[1:])
    ap = argparse.ArgumentParser(prog="busbench", description="Automotive & avionics protocol workbench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("test", help="build and run the C and Python tests")
    t.add_argument("modules", nargs="*", help="module ids, e.g. can doip")
    t.add_argument("--py", action="store_true", help="Python only, no compiler needed")
    t.add_argument("-v", "--verbose", action="store_true")
    t.add_argument("--sanitize", action="store_true", help="build C tests with ASan + UBSan")
    tr = sub.add_parser("trace", help="requirements traceability gate (exit code = problems)")
    tr.add_argument("args", nargs=argparse.REMAINDER)
    d = sub.add_parser("demo", help="run one module's demo")
    d.add_argument("module", choices=sorted(BY_ID))
    s = sub.add_parser("serve", help="REST API + Studio on localhost")
    s.add_argument("--port", type=int, default=8770)
    g = sub.add_parser("studio", help="desktop GUI")
    g.add_argument("--port", type=int, default=8770)
    a = ap.parse_args(argv)

    if a.cmd == "test":
        from busbench.runner import print_report, run_all
        report = run_all(a.modules or None, a.py, sanitize=a.sanitize)
        print_report(report, a.verbose)
        return 1 if report.failures else 0
    if a.cmd == "demo":
        mod, fn = DEMOS[a.module].split(":")
        func = getattr(importlib.import_module(f"busbench.{a.module}.{mod}"), fn)
        if a.module == "can":                  # the decoder takes the DBC and log as arguments
            data = Path(__file__).parent / "can" / "data"
            return func(["", str(data / "example.dbc"), str(data / "example.log")])
        if a.module == "arinc429":
            return func([""])
        if a.module == "traceability":         # a build gate: exit code = number of problems
            return func([])
        func()
        return 0
    if a.cmd == "serve":
        from busbench.server import serve
        serve(a.port)
    else:
        from busbench.studio_app import main as studio
        studio(a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
