/* libFuzzer: ISO-TP reassembly fed arbitrary CAN frames. Lengths, sequence
 * numbers and first-frame totals all come from the input. */
#include "isotp.h"

static void drop(const uint8_t *frame, uint8_t len) { (void)frame; (void)len; }

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    IsoTpRx_t rx = {0};
    size_t i = 0;
    while (i < size) {
        uint8_t len = (uint8_t)(data[i++] % 9);          /* a CAN frame holds 0..8 bytes */
        if (len > size - i) len = (uint8_t)(size - i);
        (void)IsoTp_RxFeed(&rx, data + i, len, drop);
        i += len;
    }
    return 0;
}
