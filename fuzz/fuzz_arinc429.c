/* libFuzzer: every 4 input bytes are one ARINC 429 word off the bus. */
#include "arinc429_analyzer.h"
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    static const LabelDictEntry_t dict[] = {
        {0203, "ALTITUDE", "ft", 1.0, 18}, {0210, "AIRSPEED", "kt", 0.0625, 15},
        {0212, "VERT_SPEED", "ft/min", 1.0, 16}, {0320, "HEADING", "deg", 0.01, 19},
    };
    char name[32], unit[8];
    double value;
    for (size_t i = 0; i + 4 <= size; i += 4) {
        uint32_t w;
        memcpy(&w, data + i, 4);
        (void)Arinc429_AnalyzeWord(w, dict, 4, name, unit, &value);
        (void)Arinc429_IsUsable(w);
    }
    return 0;
}
