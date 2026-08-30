"""Requirements traceability, the auditor's tool.

Answers the one question an auditor always asks: for every requirement,
which test proves it, and did that test actually run and pass?

The interesting failures are not the loud ones. A requirement whose test
was deleted, and a test annotated with a requirement id that no longer
exists, both look completely fine from one direction. They only show up
when you check the other, which is why this reads the source tree back as
well as the requirements document.

    python python/trace_tool.py --requirements data/requirements.csv \\
        --results data/results.xml --source data/src --out trace_report.md

Exits non zero when anything is untraced, which is what makes it usable
as a build gate.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

REQ_ANNOTATION = re.compile(r"@req\s+(?P<req>[A-Z]+-\d+)")
TEST_NAME = re.compile(r"\b(test_\w+)")


@dataclass
class Requirement:
    req_id: str
    description: str
    verified_by: str = ""
    status: str = "pass"


@dataclass
class TestResult:
    name: str
    passed: bool
    claimed: bool = False


@dataclass
class SourceLink:
    test_name: str
    req_id: str
    file: str


@dataclass
class Summary:
    requirements: int = 0
    orphan_requirements: list[str] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)
    failing: list[str] = field(default_factory=list)
    orphan_tests: list[str] = field(default_factory=list)
    bad_annotations: list[SourceLink] = field(default_factory=list)

    @property
    def problems(self) -> int:
        return (len(self.orphan_requirements) + len(self.not_run) + len(self.failing)
                + len(self.orphan_tests) + len(self.bad_annotations))


def load_requirements(path: str | Path) -> list[Requirement]:
    requirements = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0].startswith("REQ"):
            continue
        verified_by = parts[2] if len(parts) > 2 else ""
        requirements.append(Requirement(parts[0], parts[1], verified_by))
    return requirements


def load_results(path: str | Path) -> dict[str, TestResult]:
    """Reads JUnit XML, the format essentially every CI runner emits."""
    root = ET.parse(path).getroot()
    results: dict[str, TestResult] = {}
    for case in root.iter("testcase"):
        name = case.get("name", "")
        # A test case with a failure or error child did not pass. Anything
        # else, including a skipped one, is not a red result.
        failed = any(child.tag in ("failure", "error") for child in case)
        results[name] = TestResult(name, passed=not failed)
    return results


def scan_source_tree(path: str | Path) -> list[SourceLink]:
    """Finds '@req REQ-001' annotations and the test they sit above."""
    links = []
    for file in sorted(Path(path).rglob("*")):
        if not file.is_file():
            continue
        pending = None
        for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
            annotation = REQ_ANNOTATION.search(line)
            if annotation:
                pending = annotation["req"]
                continue
            name = TEST_NAME.search(line)
            if name and pending:
                links.append(SourceLink(name[1], pending, file.name))
                pending = None
    return links


def analyse(requirements: list[Requirement], results: dict[str, TestResult],
            links: list[SourceLink]) -> Summary:
    summary = Summary(requirements=len(requirements))
    known_ids = {r.req_id for r in requirements}

    for req in requirements:
        if not req.verified_by:
            req.status = "NO TEST"
            summary.orphan_requirements.append(req.req_id)
            continue

        result = results.get(req.verified_by)
        if result is None:
            # The document names a test that no longer exists. From the
            # requirements side this looks perfectly traced.
            req.status = "NOT RUN"
            summary.not_run.append(req.req_id)
            continue

        result.claimed = True
        if not result.passed:
            req.status = "FAIL"
            summary.failing.append(req.req_id)

    summary.orphan_tests = [t.name for t in results.values() if not t.claimed]
    summary.bad_annotations = [ln for ln in links if ln.req_id not in known_ids]
    return summary


def write_report(requirements: list[Requirement], summary: Summary,
                 out_path: str | Path) -> None:
    lines = ["# Traceability Matrix", "",
             "| Requirement | Verified by | Status |", "| --- | --- | --- |"]
    for req in requirements:
        lines.append(f"| {req.req_id} | {req.verified_by or '(none)'} | {req.status} |")

    lines += ["", "## Tests that no requirement asks for", ""]
    lines += [f"- {name}" for name in summary.orphan_tests] or ["- none"]

    lines += ["", "## Source annotations pointing at a missing requirement", ""]
    lines += [f"- {ln.test_name} in {ln.file} claims {ln.req_id}, "
              f"which is not in the requirements" for ln in summary.bad_annotations] or ["- none"]

    lines += ["", "## Summary", "",
              f"- requirements: {summary.requirements}",
              f"- with no test: {len(summary.orphan_requirements)}",
              f"- test named but never ran: {len(summary.not_run)}",
              f"- currently failing: {len(summary.failing)}",
              f"- tests nothing asks for: {len(summary.orphan_tests)}",
              f"- stale source annotations: {len(summary.bad_annotations)}", ""]

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requirements", default=root / "data" / "requirements.csv")
    parser.add_argument("--results", default=root / "data" / "results.xml")
    parser.add_argument("--source", default=root / "data" / "src")
    parser.add_argument("--out", default=root / "trace_report.md")
    args = parser.parse_args(argv)

    requirements = load_requirements(args.requirements)
    results = load_results(args.results)
    links = scan_source_tree(args.source)
    summary = analyse(requirements, results, links)
    write_report(requirements, summary, args.out)

    print(f"requirements       {summary.requirements}")
    print(f"no test            {len(summary.orphan_requirements)}")
    print(f"named but not run  {len(summary.not_run)}")
    print(f"failing            {len(summary.failing)}")
    print(f"unclaimed tests    {len(summary.orphan_tests)}")
    print(f"stale annotations  {len(summary.bad_annotations)}")
    print(f"\nreport written to {args.out}")

    # Non zero when anything is untraced, so CI can fail the build on it.
    return summary.problems


if __name__ == "__main__":
    sys.exit(main())
