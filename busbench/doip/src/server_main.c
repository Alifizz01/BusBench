/* Runs the gateway for real, with a small UDS responder standing in for
 * the ECUs that would sit on the CAN side. */

#include "doip_gateway.h"
#include <string.h>

static void tiny_ecu(const uint8_t *req, uint16_t req_len,
                     uint8_t *resp, uint16_t resp_cap, uint16_t *resp_len)
{
    *resp_len = 0;
    if (req_len < 1 || resp_cap < 32) return;

    if (req[0] == 0x10 && req_len >= 2) {              /* session control */
        resp[0] = 0x50; resp[1] = req[1];
        *resp_len = 2;
        return;
    }
    if (req[0] == 0x22 && req_len >= 3) {              /* read by identifier */
        uint16_t did = (uint16_t)((req[1] << 8) | req[2]);
        if (did == 0xF190) {
            resp[0] = 0x62; resp[1] = req[1]; resp[2] = req[2];
            memcpy(&resp[3], "WVWZZZ1JZ3W386752", 17);
            *resp_len = 20;
            return;
        }
    }
    resp[0] = 0x7F; resp[1] = req[0]; resp[2] = 0x11;  /* serviceNotSupported */
    *resp_len = 3;
}

int main(void)
{
    DoipGateway_SetUdsHandler(tiny_ecu);
    return DoipGateway_Start(DOIP_TCP_PORT) ? 0 : 1;
}
