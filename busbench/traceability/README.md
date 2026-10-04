# 09 DO-178C Traceability Tool

Not embedded code this time. This is the auditor's tool: it reads a
requirements file, a source tree, and a test results file, and answers the one
question an audit always asks. For every requirement, which test proves it, and
did that test actually run and pass?

## Why it reads the source tree as well

Tracing only from the requirements document leaves you trusting the document.
Two gaps look completely fine from that direction:

* **A requirement whose test was deleted.** The document still names a test, so
  the matrix shows a link. The test never runs. Reported as `NOT RUN`, which is
  worse than `NO TEST` because it looks covered.
* **A test annotated with a requirement id that no longer exists.** Someone
  renumbered or deleted the requirement and left the test behind. Only visible
  by reading the code back.

Both are in the sample data on purpose.

## What it reports

| Finding | Meaning |
| --- | --- |
| `NO TEST` | Nothing verifies this requirement |
| `NOT RUN` | Verified by a test that never executed |
| `FAIL` | Verified by a test that is currently red |
| Unclaimed test | A test that no requirement asks for |
| Stale annotation | Source claims a requirement that is gone |

Exit code is the number of problems, so it drops straight into CI as a gate.
Zero means fully traced and green, and there is a test for the zero case too,
because a tool that can only ever say no is useless.

## Run it

```
busbench test traceability              # build + run the C and Python tests
busbench demo traceability              # run the demo
```

Both write `trace_report.md` and both reach the same verdict on the sample
data: 4 requirements, 5 problems.

Point it at real inputs:

```
busbench trace --requirements reqs.csv --results junit.xml \
    --source ./tests --out report.md
```

The Python tool also accepts several tests per requirement (`test_a; test_b`, all must
pass) and several `--source` trees. BusBench uses exactly this to trace **itself**: see
[`requirements/busbench_requirements.csv`](../../requirements/busbench_requirements.csv)
and the `traceability` job in CI.

## Simplifications

The C build reads JUnit XML with string scanning rather than a parser, which is
enough for `<testcase name=...>` and a `<failure>` child but is not a general
XML reader. Python uses `ElementTree` and is the version to point at real data.
The source scan takes the first `test_*` identifier after an `@req` tag, which
is the convention the sample uses; it is not a language parser.
