/* libFuzzer: one DoIP message straight from the network into the gateway
 * state machine. The length field is a lie as often as not. */
#include <stddef.h>
#include "doip_gateway.h"

static void echo_ecu(const uint8_t *req, uint16_t req_len,
                     uint8_t *resp, uint16_t resp_cap, uint16_t *resp_len)
{
    *resp_len = 0;
    if (req_len && resp_cap >= 3) { resp[0] = 0x7F; resp[1] = req[0]; resp[2] = 0x11; *resp_len = 3; }
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    static int once;
    if (!once) { DoipGateway_SetUdsHandler(echo_ecu); once = 1; }
    uint8_t out[4200];
    /* first byte decides whether routing is already active, to reach the diag path */
    if (size && (data[0] & 1)) {
        static const uint8_t act[] = {2, 0xFD, 0, 5, 0, 0, 0, 7, 0x0E, 0, 0, 0, 0, 0, 0};
        (void)DoipGateway_HandleMessage(act, sizeof act, out, sizeof out);
    } else {
        DoipGateway_ResetSession();
    }
    (void)DoipGateway_HandleMessage(size ? data + 1 : data, size ? (uint32_t)size - 1 : 0, out, sizeof out);
    return 0;
}
