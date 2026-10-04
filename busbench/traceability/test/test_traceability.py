from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from busbench.traceability import trace as trace_tool

DATA = ROOT / "data"


def build():
    requirements = trace_tool.load_requirements(DATA / "requirements.csv")
    results = trace_tool.load_results(DATA / "results.xml")
    links = trace_tool.scan_source_tree(DATA / "src")
    return requirements, results, links


# @req REQ-1101
def test_requirements_parse():
    requirements, _, _ = build()
    assert len(requirements) == 4
    assert requirements[0].req_id == "REQ-001"
    # An empty verified_by column must stay empty rather than picking up
    # whatever came next.
    assert requirements[2].verified_by == ""


# @req REQ-1101
def test_junit_results_parse():
    _, results, _ = build()
    assert results["test_brake_applies"].passed
    assert not results["test_brake_releases"].passed


# @req REQ-1101
def test_source_annotations_are_found():
    _, _, links = build()
    assert len(links) == 3
    assert ("test_speed_limit_warning", "REQ-017") in [(ln.test_name, ln.req_id) for ln in links]


# @req REQ-1101
def test_every_kind_of_gap_is_reported():
    requirements, results, links = build()
    summary = trace_tool.analyse(requirements, results, links)

    assert summary.orphan_requirements == ["REQ-003"]   # nothing verifies it
    assert summary.failing == ["REQ-002"]               # its test is red
    assert summary.not_run == ["REQ-004"]               # named a test that never ran
    assert summary.orphan_tests == ["test_speed_limit_warning"]
    assert [ln.req_id for ln in summary.bad_annotations] == ["REQ-017"]
    assert summary.problems == 5


# @req REQ-1102
def test_a_clean_project_exits_zero():
    """The tool has to be able to say yes, otherwise it is useless as a
    build gate."""
    requirements = [trace_tool.Requirement("REQ-001", "something", "test_ok")]
    results = {"test_ok": trace_tool.TestResult("test_ok", passed=True)}
    links = [trace_tool.SourceLink("test_ok", "REQ-001", "test_ok.py")]

    summary = trace_tool.analyse(requirements, results, links)
    assert summary.problems == 0
    assert requirements[0].status == "pass"


# @req REQ-1102
def test_report_matches_the_c_implementation():
    """Both tools read the same inputs and must reach the same verdict."""
    requirements, results, links = build()
    summary = trace_tool.analyse(requirements, results, links)
    statuses = {r.req_id: r.status for r in requirements}
    assert statuses == {
        "REQ-001": "pass",
        "REQ-002": "FAIL",
        "REQ-003": "NO TEST",
        "REQ-004": "NOT RUN",
    }


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all assertions passed")
