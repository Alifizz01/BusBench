/* Requirements traceability.
 *
 * The tool answers one question an auditor always asks: for every
 * requirement, which test proves it, and did that test actually run and
 * pass? The interesting failures are not the loud ones. A requirement
 * whose test was deleted, and a test annotated with a requirement id
 * that no longer exists, both look completely fine from one direction
 * and only show up when you check the other. */

#include "trace_tool.h"
#include <stdio.h>
#include <string.h>
#include <ctype.h>

#ifdef _MSC_VER                   /* MSVC has no dirent.h */
  #define WIN32_LEAN_AND_MEAN
  #include <windows.h>
#else
  #include <dirent.h>
#endif

static TestResult_t tests[TRACE_MAX_TESTS];
static int          test_count;

static SourceLink_t links[TRACE_MAX_LINKS];
static int          link_count;

static TraceSummary_t summary;

void Trace_GetSummary(TraceSummary_t *out) { if (out) *out = summary; }

static char *trim(char *s)
{
    while (*s && isspace((unsigned char)*s)) s++;
    char *end = s + strlen(s);
    while (end > s && isspace((unsigned char)end[-1])) *--end = '\0';
    return s;
}

int Trace_LoadRequirements(const char *csv_path, Requirement_t *out, int max_reqs)
{
    FILE *f = fopen(csv_path, "r");
    if (!f) return -1;

    char line[512];
    int n = 0;

    while (fgets(line, sizeof line, f) && n < max_reqs) {
        if (line[0] == '#' || line[0] == '\n') continue;

        char *id = strtok(line, ",");
        char *desc = strtok(NULL, ",");
        char *test = strtok(NULL, ",\n");
        if (!id || !desc) continue;

        id = trim(id);
        if (strncmp(id, "REQ", 3) != 0) continue;      /* header row or junk */

        Requirement_t *r = &out[n++];
        memset(r, 0, sizeof *r);
        snprintf(r->req_id, sizeof r->req_id, "%s", id);
        snprintf(r->description, sizeof r->description, "%s", trim(desc));
        if (test) snprintf(r->verified_by, sizeof r->verified_by, "%s", trim(test));
    }

    fclose(f);
    return n;
}

/* A deliberately small JUnit reader: find each <testcase name="...">, then
 * decide whether it failed by looking for a <failure or <error before the
 * case closes. That is all a traceability tool needs from the format. */
static int load_junit(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    static char xml[1 << 18];
    size_t len = fread(xml, 1, sizeof xml - 1, f);
    xml[len] = '\0';
    fclose(f);

    test_count = 0;
    const char *p = xml;

    while ((p = strstr(p, "<testcase")) != NULL && test_count < TRACE_MAX_TESTS) {
        const char *name = strstr(p, "name=\"");
        const char *end_tag = strchr(p, '>');
        if (!name || !end_tag || name > end_tag) { p += 9; continue; }

        name += 6;
        const char *name_end = strchr(name, '"');
        if (!name_end) break;

        TestResult_t *t = &tests[test_count++];
        memset(t, 0, sizeof *t);
        size_t n = (size_t)(name_end - name);
        if (n >= sizeof t->name) n = sizeof t->name - 1;
        memcpy(t->name, name, n);

        /* Self closing <testcase ... /> means it passed. Otherwise look
         * inside the element for a failure or error child. */
        if (end_tag[-1] == '/') {
            t->passed = true;
        } else {
            const char *close = strstr(end_tag, "</testcase>");
            const char *fail = strstr(end_tag, "<failure");
            const char *err  = strstr(end_tag, "<error");
            bool bad = (fail && (!close || fail < close)) ||
                       (err  && (!close || err  < close));
            t->passed = !bad;
        }
        p = end_tag;
    }

    return test_count;
}

static TestResult_t *find_test(const char *name)
{
    for (int i = 0; i < test_count; i++)
        if (strcmp(tests[i].name, name) == 0) return &tests[i];
    return NULL;
}

void Trace_CrossReferenceResults(Requirement_t *reqs, int count, const char *results_path)
{
    if (load_junit(results_path) < 0) return;

    for (int i = 0; i < count; i++) {
        reqs[i].test_passed = false;
        if (reqs[i].verified_by[0] == '\0') continue;

        TestResult_t *t = find_test(reqs[i].verified_by);
        if (!t) continue;              /* named but never ran, caught in the report */
        t->claimed = true;
        reqs[i].test_passed = t->passed;
    }
}

/* Looks for "@req REQ-0042" anywhere in a file, and takes the nearest
 * following identifier that starts with "test" as the test name. */
static void scan_file(const char *path, const char *filename)
{
    FILE *f = fopen(path, "r");
    if (!f) return;

    char line[512];
    char pending_req[16] = "";

    while (fgets(line, sizeof line, f)) {
        char *tag = strstr(line, "@req");
        if (tag) {
            char id[16] = "";
            if (sscanf(tag + 4, " %15s", id) == 1)
                snprintf(pending_req, sizeof pending_req, "%s", id);
            continue;
        }

        char *t = strstr(line, "test_");
        if (t && pending_req[0] && link_count < TRACE_MAX_LINKS) {
            char name[64] = "";
            size_t i = 0;
            while (i < sizeof name - 1 && (isalnum((unsigned char)t[i]) || t[i] == '_'))
                { name[i] = t[i]; i++; }
            name[i] = '\0';

            SourceLink_t *l = &links[link_count++];
            snprintf(l->test_name, sizeof l->test_name, "%s", name);
            snprintf(l->req_id, sizeof l->req_id, "%s", pending_req);
            snprintf(l->file, sizeof l->file, "%s", filename);
            pending_req[0] = '\0';
        }
    }

    fclose(f);
}

int Trace_ScanSourceTree(const char *dir_path)
{
    char path[512];
    link_count = 0;

#ifdef _MSC_VER
    WIN32_FIND_DATAA entry;
    char pattern[512];
    snprintf(pattern, sizeof pattern, "%s/*", dir_path);
    HANDLE d = FindFirstFileA(pattern, &entry);
    if (d == INVALID_HANDLE_VALUE) return -1;
    do {
        if (entry.cFileName[0] == '.') continue;
        snprintf(path, sizeof path, "%s/%s", dir_path, entry.cFileName);
        scan_file(path, entry.cFileName);
    } while (FindNextFileA(d, &entry));
    FindClose(d);
#else
    DIR *d = opendir(dir_path);
    if (!d) return -1;
    struct dirent *entry;
    while ((entry = readdir(d)) != NULL) {
        if (entry->d_name[0] == '.') continue;
        snprintf(path, sizeof path, "%s/%s", dir_path, entry->d_name);
        scan_file(path, entry->d_name);
    }
    closedir(d);
#endif
    return link_count;
}

int Trace_GenerateReport(const Requirement_t *reqs, int count, const char *report_out_path)
{
    FILE *f = fopen(report_out_path, "w");
    if (!f) return -1;

    memset(&summary, 0, sizeof summary);
    summary.requirements = count;

    fprintf(f, "# Traceability Matrix\n\n");
    fprintf(f, "| Requirement | Verified by | Status |\n");
    fprintf(f, "| --- | --- | --- |\n");

    for (int i = 0; i < count; i++) {
        const char *status;

        if (reqs[i].verified_by[0] == '\0') {
            status = "NO TEST";
            summary.orphan_requirements++;
        } else if (!find_test(reqs[i].verified_by)) {
            /* The document names a test that no longer exists. From the
             * requirements side this looks perfectly traced. */
            status = "NOT RUN";
            summary.not_run++;
        } else if (!reqs[i].test_passed) {
            status = "FAIL";
            summary.failing++;
        } else {
            status = "pass";
        }

        fprintf(f, "| %s | %s | %s |\n", reqs[i].req_id,
                reqs[i].verified_by[0] ? reqs[i].verified_by : "(none)", status);
    }

    fprintf(f, "\n## Tests that no requirement asks for\n\n");
    for (int i = 0; i < test_count; i++) {
        if (tests[i].claimed) continue;
        summary.orphan_tests++;
        fprintf(f, "- %s\n", tests[i].name);
    }
    if (summary.orphan_tests == 0) fprintf(f, "- none\n");

    fprintf(f, "\n## Source annotations pointing at a missing requirement\n\n");
    for (int i = 0; i < link_count; i++) {
        bool found = false;
        for (int j = 0; j < count; j++)
            if (strcmp(links[i].req_id, reqs[j].req_id) == 0) { found = true; break; }
        if (found) continue;
        summary.bad_annotations++;
        fprintf(f, "- %s in %s claims %s, which is not in the requirements\n",
                links[i].test_name, links[i].file, links[i].req_id);
    }
    if (summary.bad_annotations == 0) fprintf(f, "- none\n");

    fprintf(f, "\n## Summary\n\n");
    fprintf(f, "- requirements: %d\n", summary.requirements);
    fprintf(f, "- with no test: %d\n", summary.orphan_requirements);
    fprintf(f, "- test named but never ran: %d\n", summary.not_run);
    fprintf(f, "- currently failing: %d\n", summary.failing);
    fprintf(f, "- tests nothing asks for: %d\n", summary.orphan_tests);
    fprintf(f, "- stale source annotations: %d\n", summary.bad_annotations);

    fclose(f);

    /* Zero only if every requirement is verified by a test that ran and
     * passed, and nothing is dangling in either direction. */
    return summary.orphan_requirements + summary.not_run + summary.failing +
           summary.orphan_tests + summary.bad_annotations;
}
