#include "trace_tool.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

int main(void)
{
    Requirement_t reqs[TRACE_MAX_REQS];

    int n = Trace_LoadRequirements("data/requirements.csv", reqs, TRACE_MAX_REQS);
    assert(n == 4);
    assert(strcmp(reqs[0].req_id, "REQ-001") == 0);
    /* REQ-003 has an empty verified_by field, which must survive parsing
     * as empty rather than picking up the next column. */
    assert(reqs[2].verified_by[0] == '\0');

    int links = Trace_ScanSourceTree("data/src");
    assert(links == 3);

    Trace_CrossReferenceResults(reqs, n, "data/results.xml");
    assert(reqs[0].test_passed);        /* REQ-001, green */
    assert(!reqs[1].test_passed);       /* REQ-002, its test failed */

    int problems = Trace_GenerateReport(reqs, n, "trace_report.md");

    TraceSummary_t s;
    Trace_GetSummary(&s);

    assert(s.requirements == 4);
    assert(s.orphan_requirements == 1);   /* REQ-003 has no test at all */
    assert(s.failing == 1);               /* REQ-002 is red */
    assert(s.not_run == 1);               /* REQ-004 names a test that never ran */
    assert(s.orphan_tests == 1);          /* test_speed_limit_warning */
    assert(s.bad_annotations == 1);       /* a test claims REQ-017, which is gone */
    assert(problems == 5);

    printf("requirements       %d\n", s.requirements);
    printf("no test            %d\n", s.orphan_requirements);
    printf("named but not run  %d\n", s.not_run);
    printf("failing            %d\n", s.failing);
    printf("unclaimed tests    %d\n", s.orphan_tests);
    printf("stale annotations  %d\n", s.bad_annotations);
    printf("\nreport written to trace_report.md, exit code would be %d\n", problems);

    printf("\nall assertions passed\n");
    return 0;
}
