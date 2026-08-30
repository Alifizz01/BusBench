#ifndef TRACE_TOOL_H
#define TRACE_TOOL_H
/* Project 9: DO-178C / ISO 26262 Requirements Traceability Tool.
 * Goal: NOT embedded C this time - a small tool (can be C or a script)
 * that parses a requirements CSV + a source tree + a test-results file
 * and produces a traceability matrix report, flagging: requirements
 * with no test, tests with no requirement, and requirements whose
 * linked test currently fails. This is the "auditor's tool" every
 * certified-software team has an internal version of. */

#include <stdint.h>
#include <stdbool.h>

#define TRACE_MAX_REQS    256
#define TRACE_MAX_TESTS   256
#define TRACE_MAX_LINKS   256

typedef struct {
    char req_id[16];
    char description[128];
    char verified_by[64];   /* test function/file name, or empty = orphan */
    bool test_passed;        /* filled in after cross-referencing test results */
} Requirement_t;

/* added: one entry per test case found in the results file. */
typedef struct {
    char name[64];
    bool passed;
    bool claimed;            /* true once some requirement points at it */
} TestResult_t;

/* added: an "@req REQ-001" annotation found in a source file. Tracing
 * only from the document leaves you trusting it; reading the code back
 * is how a wrong or stale link gets found. */
typedef struct {
    char test_name[64];
    char req_id[16];
    char file[128];
} SourceLink_t;

/* added: what the report counted, so a build can fail on a number. */
typedef struct {
    int requirements;
    int orphan_requirements;   /* nothing verifies them */
    int orphan_tests;          /* nothing asks for them */
    int failing;               /* verified by a test that is currently red */
    int not_run;               /* verified by a test that never executed */
    int bad_annotations;       /* source points at a requirement that is gone */
} TraceSummary_t;

int  Trace_LoadRequirements(const char *csv_path, Requirement_t *out, int max_reqs);

/* Scans a test-results file (e.g. JUnit XML or a simple pass/fail list)
 * and marks each requirement's test_passed field. */
void Trace_CrossReferenceResults(Requirement_t *reqs, int count, const char *results_path);

/* added: reads the source tree for "@req" annotations, giving the other
 * direction of the trace. Optional; skip it and that check is skipped. */
int  Trace_ScanSourceTree(const char *dir_path);

/* Produces the final report: counts of orphan requirements, orphan
 * tests, and failing-but-required tests. Returns 0 = fully traced & green. */
int  Trace_GenerateReport(const Requirement_t *reqs, int count, const char *report_out_path);

/* added: the same numbers the report printed. */
void Trace_GetSummary(TraceSummary_t *out);

#endif /* TRACE_TOOL_H */
