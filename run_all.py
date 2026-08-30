#!/usr/bin/env python3
"""Builds and runs every project in the portfolio, C and Python.

    python run_all.py            # everything
    python run_all.py --py       # Python only, no compiler needed
    python run_all.py 02 05      # just those projects

Works from any shell. If no C compiler is found the C half is skipped and
reported as skipped rather than quietly passing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Windows needs the sockets library for project 5. Both extra libraries are
# harmless everywhere else they are passed.
EXTRA_LIBS = ["-lm"] + (["-lws2_32"] if os.name == "nt" else [])

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def find_compiler() -> str | None:
    for name in ("gcc", "cc", "clang"):
        found = shutil.which(name)
        if found:
            return found
    # MSYS2 installs a perfectly good gcc that is often not on PATH.
    for candidate in (r"C:\msys64\mingw64\bin\gcc.exe", r"C:\msys64\ucrt64\bin\gcc.exe"):
        if Path(candidate).exists():
            return candidate
    return None


def projects(filters: list[str]) -> list[Path]:
    found = sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name[:2].isdigit())
    if not filters:
        return found
    return [p for p in found if any(p.name.startswith(f) for f in filters)]


def c_sources(project: Path) -> list[Path]:
    """Everything in src/ except files with their own main()."""
    return [f for f in sorted((project / "src").glob("*.c")) if not f.name.endswith("_main.c")]


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[bool, str]:
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=120, env=env)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except OSError as exc:
        return False, str(exc)
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("filters", nargs="*", help="project number prefixes, e.g. 02 05")
    parser.add_argument("--py", action="store_true", help="Python tests only")
    parser.add_argument("-v", "--verbose", action="store_true", help="show test output")
    args = parser.parse_args(argv)

    compiler = None if args.py else find_compiler()
    if not args.py and compiler is None:
        print(f"{YELLOW}no C compiler found, running the Python half only{RESET}\n")

    # A compiler found outside PATH (the MSYS2 case) cannot load its own
    # DLLs unless its directory is on PATH, and it fails silently if not.
    env = None
    if compiler and not shutil.which(Path(compiler).name):
        env = dict(os.environ)
        env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")

    results: list[tuple[str, str, str, str]] = []

    for project in projects(args.filters):
        name = project.name
        c_status, py_status = "skip", "skip"

        # --- C ---
        sources = c_sources(project)
        c_tests = sorted((project / "test").glob("test_*.c"))
        if compiler and sources and c_tests:
            build = project / "build"
            build.mkdir(exist_ok=True)
            binary = build / "run_tests.exe"

            cmd = [compiler, "-std=c11", "-Wall", "-Wextra", "-Iinclude"]
            cmd += [str(f.relative_to(project)) for f in sources]
            cmd += [str(c_tests[0].relative_to(project))]
            cmd += ["-o", str(binary.relative_to(project))] + EXTRA_LIBS

            built, output = run(cmd, project, env)
            if not built:
                c_status, detail = "FAIL", output
            else:
                passed, detail = run([str(binary)], project, env)
                c_status = "pass" if passed else "FAIL"
            if args.verbose or c_status == "FAIL":
                print(f"{DIM}--- {name} (C) ---{RESET}\n{detail}\n")

        # --- Python ---
        py_tests = sorted((project / "test").glob("test_*.py"))
        if py_tests:
            passed, detail = run([sys.executable, str(py_tests[0].relative_to(project))], project)
            py_status = "pass" if passed else "FAIL"
            if args.verbose or py_status == "FAIL":
                print(f"{DIM}--- {name} (Python) ---{RESET}\n{detail}\n")

        results.append((name, c_status, py_status, ""))

    def paint(status: str) -> str:
        colour = {"pass": GREEN, "FAIL": RED}.get(status, YELLOW)
        return f"{colour}{status:<5}{RESET}"

    print(f"{'project':<32} {'C':<6} {'Python':<6}")
    print("-" * 46)
    for name, c_status, py_status, _ in results:
        print(f"{name:<32} {paint(c_status)}  {paint(py_status)}")

    failures = sum(1 for _, c, p, _ in results if "FAIL" in (c, p))
    print("-" * 46)
    print(f"{len(results)} projects, {failures} with failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
