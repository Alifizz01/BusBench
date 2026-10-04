"""Builds and runs every module's tests, C and Python, plus the C <-> Python
DoIP interop check. Used by `busbench test`, the Studio overview and CI.

Finds a compiler on its own: gcc / cc / clang on PATH, an MSYS2 gcc that is
not on PATH, or MSVC through vswhere. No compiler means the C half is
reported as skipped, never as passed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from busbench.modules import MODULES

PKG = Path(__file__).resolve().parent
REPO = PKG.parent


@dataclass
class Compiler:
    kind: str                 # "gcc" (gcc/cc/clang flags) or "msvc"
    path: str
    env: dict | None = None

    @property
    def label(self) -> str:
        return "MSVC cl" if self.kind == "msvc" else Path(self.path).stem


@dataclass
class ModuleResult:
    module: str
    c: str = "skip"           # pass | FAIL | skip
    py: str = "skip"
    interop: str = ""         # only for doip: pass | FAIL | skip
    c_log: str = ""
    py_log: str = ""
    interop_log: str = ""
    seconds: float = 0.0


@dataclass
class Report:
    compiler: str | None
    results: list[ModuleResult] = field(default_factory=list)

    @property
    def failures(self) -> int:
        return sum(1 for r in self.results if "FAIL" in (r.c, r.py, r.interop))

    def to_dict(self) -> dict:
        return {"compiler": self.compiler, "failures": self.failures,
                "results": [asdict(r) for r in self.results]}


def _msvc() -> Compiler | None:
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                   "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not vswhere.exists():
        return None
    out = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                          "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                          "-property", "installationPath"], capture_output=True, text=True)
    vcvars = Path(out.stdout.strip(), "VC", "Auxiliary", "Build", "vcvars64.bat")
    if not out.stdout.strip() or not vcvars.exists():
        return None
    # Run vcvars once and keep the environment it produces.
    dump = subprocess.run(f'cmd /s /c ""{vcvars}" >nul && set"', capture_output=True, text=True, shell=True)
    env = dict(line.split("=", 1) for line in dump.stdout.splitlines() if "=" in line)
    cl = shutil.which("cl", path=env.get("PATH") or env.get("Path"))
    return Compiler("msvc", cl, env) if cl else None


def find_compiler() -> Compiler | None:
    """BUSBENCH_CC=gcc|clang|msvc|<path> forces a choice (used by the CI matrix)."""
    forced = os.environ.get("BUSBENCH_CC")
    if forced:
        if forced == "msvc":
            return _msvc()
        path = shutil.which(forced)
        return Compiler("gcc", path) if path else None
    for name in ("gcc", "cc", "clang"):
        if shutil.which(name):
            return Compiler("gcc", shutil.which(name))
    for candidate in (r"C:\msys64\mingw64\bin\gcc.exe", r"C:\msys64\ucrt64\bin\gcc.exe"):
        if Path(candidate).exists():
            env = dict(os.environ)       # MSYS2 gcc needs its own dir on PATH for its DLLs
            env["PATH"] = str(Path(candidate).parent) + os.pathsep + env.get("PATH", "")
            return Compiler("gcc", candidate, env)
    return _msvc() if os.name == "nt" else None


def _run(cmd, cwd: Path, env=None, timeout=120) -> tuple[bool, str]:
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except OSError as exc:
        return False, str(exc)
    return done.returncode == 0, (done.stdout + done.stderr).strip()


SANITIZE = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-g"]


def build(cc: Compiler, module_dir: Path, sources: list[Path], out: Path,
          sanitize: bool = False) -> tuple[bool, str]:
    """Compile `sources` (paths relative to module_dir) into `out`.
    sanitize=True adds AddressSanitizer + UBSan (gcc/clang on Linux/macOS)."""
    (module_dir / out).parent.mkdir(exist_ok=True)
    rel = [str(s) for s in sources]
    if cc.kind == "msvc":
        cmd = [cc.path, "/nologo", "/std:c11", "/W3", "/D_CRT_SECURE_NO_WARNINGS", "/Iinclude",
               *rel, f"/Fe:{out}", f"/Fo:{out.parent}{os.sep}", "ws2_32.lib"]
    else:
        cmd = [cc.path, "-std=c11", "-Wall", "-Wextra", "-Iinclude", *(SANITIZE if sanitize else []),
               *rel, "-o", str(out), "-lm"]
        if os.name == "nt":
            cmd.append("-lws2_32")
    return _run(cmd, module_dir, cc.env)


def c_sources(module_dir: Path) -> list[Path]:
    """Everything in src/ except files with their own main()."""
    return [f.relative_to(module_dir) for f in sorted((module_dir / "src").glob("*.c"))
            if not f.name.endswith("_main.c")]


def connect_retry(factory, seconds: float = 5.0):
    """Retry a connection while a freshly started server comes up. (No
    probe-then-connect: the C gateway serves exactly one tester, and a
    probe connection would use it up.)"""
    end = time.time() + seconds
    while True:
        try:
            return factory()
        except OSError:
            if time.time() > end:
                raise
            time.sleep(0.1)


def build_doip_server(cc: Compiler) -> tuple[Path | None, str]:
    module_dir = PKG / "doip"
    exe = module_dir / "build" / ("doip_server.exe" if os.name == "nt" else "doip_server")
    srcs = [f.relative_to(module_dir) for f in sorted((module_dir / "src").glob("*.c"))]
    ok, log = build(cc, module_dir, srcs, exe.relative_to(module_dir))
    return (exe if ok else None), log


def doip_interop(cc: Compiler) -> tuple[str, str]:
    """The Python tester against the C gateway, over real TCP on 13400."""
    from busbench.doip.gateway import TCP_PORT, DoipClient
    exe, log = build_doip_server(cc)
    if exe is None:
        return "FAIL", log
    proc = subprocess.Popen([str(exe)], cwd=exe.parent, env=cc.env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with connect_retry(lambda: DoipClient(port=TCP_PORT)) as tester:
            vin = tester.identify()[:17].decode()
            try:
                tester.send_uds(b"\x22\xf1\x90")
                return "FAIL", "C gateway accepted diagnostics before routing activation"
            except PermissionError:
                pass
            code = tester.activate_routing()
            answer = tester.send_uds(b"\x22\xf1\x90")[3:].decode()
        ok = vin == answer == "WVWZZZ1JZ3W386752" and code == 0x10
        return ("pass" if ok else "FAIL"), f"identify {vin}, routing 0x{code:02X}, VIN over TCP {answer}"
    except OSError as exc:
        return "FAIL", str(exc)
    finally:
        proc.terminate()
        proc.wait(5)


def run_module(name: str, cc: Compiler | None, python_only: bool = False,
               sanitize: bool = False) -> ModuleResult:
    module_dir = PKG / name
    res = ModuleResult(name)
    t0 = time.perf_counter()

    c_tests = sorted((module_dir / "test").glob("test_*.c"))
    if cc and not python_only and c_tests:
        exe = Path("build") / "run_tests.exe"
        ok, log = build(cc, module_dir, c_sources(module_dir) + [c_tests[0].relative_to(module_dir)], exe, sanitize)
        if ok:
            # Run from the module folder: the C tests read data/ relatively.
            ok, log = _run([str(module_dir / exe)], module_dir, cc.env)
        res.c, res.c_log = ("pass" if ok else "FAIL"), log

    py_tests = sorted((module_dir / "test").glob("test_*.py"))
    if py_tests:
        env = dict(os.environ, PYTHONPATH=str(REPO) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        ok, log = _run([sys.executable, str(py_tests[0])], module_dir, env)
        res.py, res.py_log = ("pass" if ok else "FAIL"), log

    if name == "doip":
        res.interop, res.interop_log = doip_interop(cc) if cc and not python_only else ("skip", "no C compiler")
    res.seconds = round(time.perf_counter() - t0, 2)
    return res


def run_all(filters: list[str] | None = None, python_only: bool = False, on_result=None,
            sanitize: bool = False) -> Report:
    cc = None if python_only else find_compiler()
    report = Report(cc.label if cc else None)
    for m in MODULES:
        if filters and not any(m.id.startswith(f) for f in filters):
            continue
        r = run_module(m.id, cc, python_only, sanitize)
        report.results.append(r)
        if on_result:
            on_result(r)
    return report


GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def print_report(report: Report, verbose: bool = False) -> None:
    def paint(s: str) -> str:
        colour = {"pass": GREEN, "FAIL": RED}.get(s, YELLOW)
        return f"{colour}{(s or '-'):<6}{RESET}"
    print(f"compiler: {report.compiler or 'none found - C half skipped'}\n")
    print(f"{'module':<14} {'C':<6} {'Python':<6} {'Interop':<7}")
    print("-" * 38)
    for r in report.results:
        print(f"{r.module:<14} {paint(r.c)} {paint(r.py)} {paint(r.interop)}")
        if verbose or "FAIL" in (r.c, r.py, r.interop):
            for part, log in (("C", r.c_log), ("Python", r.py_log), ("interop", r.interop_log)):
                if log and (verbose or "FAIL" in (r.c, r.py, r.interop)):
                    print(f"    --- {part} ---\n    " + log.replace("\n", "\n    "))
    print("-" * 38)
    print(f"{len(report.results)} modules, {report.failures} with failures")
