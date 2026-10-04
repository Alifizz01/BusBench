#include "arinc429_analyzer.h"
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <assert.h>

static int close_to(double a, double b) { return fabs(a - b) < 1e-6; }

int main(void)
{
    LabelDictEntry_t dict[16];
    uint32_t words[32];

    int nlabels = LabelDict_Load("data/labels.csv", dict, 16);
    int nwords  = Arinc429_ReadCapture("data/capture.txt", words, 32);
    assert(nlabels == 4);
    assert(nwords == 6);

    /* Labels are octal by convention, so 0203 must load as 131, not 203. */
    assert(dict[0].label_octal == 0203);

    /* The label is bit reversed on the wire. Getting this wrong gives a
     * plausible looking label for the wrong parameter entirely. */
    uint32_t w = Arinc429_BuildWord(0203, 1, 35000, ARINC_SSM_NORMAL_OPERATION, 18);
    assert(Arinc429_GetLabel(w) == 0203);
    assert((w & 0xFF) == 0xC1);          /* 0203 octal reversed is 0xC1 */
    printf("label 0203 goes on the wire as 0x%02X\n", w & 0xFF);

    /* Odd parity over all 32 bits. Flip any bit and it must fail. */
    assert(Arinc429_CheckParity(w));
    assert(!Arinc429_CheckParity(w ^ 0x00001000u));
    printf("odd parity catches a single flipped bit\n");

    char name[32], unit[8];
    double value;

    /* Round trip through the builder, at several word widths. */
    assert(Arinc429_AnalyzeWord(w, dict, nlabels, name, unit, &value));
    assert(strcmp(name, "ALTITUDE") == 0 && close_to(value, 35000.0));

    w = Arinc429_BuildWord(0210, 1, 7680, ARINC_SSM_NORMAL_OPERATION, 15);
    assert(Arinc429_AnalyzeWord(w, dict, nlabels, name, unit, &value));
    assert(close_to(value, 480.0));      /* 7680 counts at 0.0625 kt */

    /* Negative values are two's complement across the 19 bit field. */
    w = Arinc429_BuildWord(0212, 1, -2000, ARINC_SSM_NORMAL_OPERATION, 16);
    assert(Arinc429_AnalyzeWord(w, dict, nlabels, name, unit, &value));
    assert(close_to(value, -2000.0));
    printf("negative rate decodes as %.0f %s\n", value, unit);

    /* A word can decode perfectly and still be meaningless. */
    w = Arinc429_BuildWord(0210, 1, 7680, ARINC_SSM_NO_COMPUTED_DATA, 15);
    assert(Arinc429_AnalyzeWord(w, dict, nlabels, name, unit, &value));  /* decodes */
    assert(!Arinc429_IsUsable(w));                                       /* but do not use it */
    printf("SSM says no computed data, so the value is not usable\n");

    /* An unknown label must be refused, not guessed at. */
    w = Arinc429_BuildWord(0377, 0, 1, ARINC_SSM_NORMAL_OPERATION, 18);
    assert(!Arinc429_AnalyzeWord(w, dict, nlabels, name, unit, &value));

    printf("\ncaptured bus:\n");
    for (int i = 0; i < nwords; i++) {
        if (!Arinc429_CheckParity(words[i])) {
            printf("  %08X  PARITY ERROR, discarded\n", words[i]);
            continue;
        }
        if (!Arinc429_AnalyzeWord(words[i], dict, nlabels, name, unit, &value)) {
            printf("  %08X  label %03o not in dictionary\n",
                   words[i], Arinc429_GetLabel(words[i]));
            continue;
        }
        printf("  %08X  %-11s %10.2f %-7s %s\n", words[i], name, value, unit,
               Arinc429_IsUsable(words[i]) ? "" : "<- SSM not normal, ignore");
    }

    printf("\nall assertions passed\n");
    return 0;
}
