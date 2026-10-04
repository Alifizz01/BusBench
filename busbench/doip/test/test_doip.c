/* Protocol tests with no sockets involved. Every case is a buffer in and
 * a buffer out, which is the reason the framing lives in its own file. */

#include "doip_gateway.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

static void tiny_ecu(const uint8_t *req, uint16_t req_len,
                     uint8_t *resp, uint16_t resp_cap, uint16_t *resp_len)
{
    (void)resp_cap;
    *resp_len = 0;
    if (req_len >= 3 && req[0] == 0x22 && req[1] == 0xF1 && req[2] == 0x90) {
        resp[0] = 0x62; resp[1] = 0xF1; resp[2] = 0x90;
        memcpy(&resp[3], "WVWZZZ1JZ3W386752", 17);
        *resp_len = 20;
    }
}

static uint16_t type_of(const uint8_t *frame) { return (uint16_t)((frame[2] << 8) | frame[3]); }

int main(void)
{
    uint8_t msg[256], out[256];
    int n;

    DoipGateway_SetUdsHandler(tiny_ecu);
    DoipGateway_ResetSession();

    /* Header round trip. */
    uint8_t payload[3] = { 1, 2, 3 };
    n = Doip_Build(DOIP_DIAG_MESSAGE, payload, 3, msg, sizeof msg);
    assert(n == DOIP_HEADER_LEN + 3);
    uint16_t type; uint32_t plen;
    assert(Doip_ParseHeader(msg, (uint32_t)n, &type, &plen) == DOIP_HEADER_LEN);
    assert(type == DOIP_DIAG_MESSAGE && plen == 3);

    /* Byte 1 must be the complement of byte 0. Corrupt it and the whole
     * message is refused before anything in it is believed. */
    msg[1] = 0x00;
    n = DoipGateway_HandleMessage(msg, DOIP_HEADER_LEN + 3, out, sizeof out);
    assert(n > 0 && type_of(out) == DOIP_GENERIC_NACK && out[8] == DOIP_NACK_INCORRECT_PATTERN);
    printf("bad protocol version rejected\n");

    /* A header claiming more bytes than arrived must not be believed.
     * This is the classic buffer overrun in every parser. */
    n = Doip_Build(DOIP_DIAG_MESSAGE, payload, 3, msg, sizeof msg);
    msg[7] = 200;                                   /* claim 200 bytes, send 3 */
    n = DoipGateway_HandleMessage(msg, DOIP_HEADER_LEN + 3, out, sizeof out);
    assert(n > 0 && type_of(out) == DOIP_GENERIC_NACK && out[8] == DOIP_NACK_INVALID_LENGTH);
    printf("lying length field rejected\n");

    /* Vehicle identification works before routing activation, because it
     * is how the tester finds out what it is plugged into. */
    n = Doip_Build(DOIP_VEHICLE_IDENT_REQ, NULL, 0, msg, sizeof msg);
    n = DoipGateway_HandleMessage(msg, (uint32_t)n, out, sizeof out);
    assert(n == DOIP_HEADER_LEN + 32 && type_of(out) == DOIP_VEHICLE_IDENT_RESP);
    assert(memcmp(&out[8], "WVWZZZ1JZ3W386752", 17) == 0);
    printf("vehicle identification: %.17s\n", &out[8]);

    /* Diagnostics before routing activation must be refused. This is the
     * check the whole state machine exists for. */
    uint8_t diag[7] = { 0x0E, 0x00, 0x00, 0x10, 0x22, 0xF1, 0x90 };
    n = Doip_Build(DOIP_DIAG_MESSAGE, diag, 7, msg, sizeof msg);
    n = DoipGateway_HandleMessage(msg, (uint32_t)n, out, sizeof out);
    assert(n > 0 && type_of(out) == DOIP_DIAG_NACK);
    assert(!DoipGateway_IsRoutingActive());
    printf("UDS before routing activation refused\n");

    /* Source address 0x0000 is not a tester. */
    uint8_t act_bad[7] = { 0x00, 0x00, 0x00, 0, 0, 0, 0 };
    n = Doip_Build(DOIP_ROUTING_ACTIVATION_REQ, act_bad, 7, msg, sizeof msg);
    n = DoipGateway_HandleMessage(msg, (uint32_t)n, out, sizeof out);
    assert(n > 0 && out[12] == DOIP_ROUTING_UNKNOWN_SOURCE);
    assert(!DoipGateway_IsRoutingActive());

    /* A real tester activates and then gets served. */
    uint8_t act[7] = { 0x0E, 0x00, 0x00, 0, 0, 0, 0 };
    n = Doip_Build(DOIP_ROUTING_ACTIVATION_REQ, act, 7, msg, sizeof msg);
    n = DoipGateway_HandleMessage(msg, (uint32_t)n, out, sizeof out);
    assert(n > 0 && type_of(out) == DOIP_ROUTING_ACTIVATION_RESP);
    assert(out[12] == DOIP_ROUTING_SUCCESS);
    assert(DoipGateway_IsRoutingActive());
    printf("routing activated for tester 0x0E00\n");

    n = Doip_Build(DOIP_DIAG_MESSAGE, diag, 7, msg, sizeof msg);
    n = DoipGateway_HandleMessage(msg, (uint32_t)n, out, sizeof out);
    assert(n > 0 && type_of(out) == DOIP_DIAG_MESSAGE);
    assert(memcmp(&out[15], "WVWZZZ1JZ3W386752", 17) == 0);
    printf("UDS forwarded, VIN came back: %.17s\n", &out[15]);

    /* A different source address is still refused after activation. */
    uint8_t other[7] = { 0x0E, 0x01, 0x00, 0x10, 0x22, 0xF1, 0x90 };
    n = Doip_Build(DOIP_DIAG_MESSAGE, other, 7, msg, sizeof msg);
    n = DoipGateway_HandleMessage(msg, (uint32_t)n, out, sizeof out);
    assert(n > 0 && type_of(out) == DOIP_DIAG_NACK);
    printf("a second tester cannot ride the first activation\n");

    /* An unknown payload type gets a defined answer, not silence. */
    n = Doip_Build(0x1234, NULL, 0, msg, sizeof msg);
    n = DoipGateway_HandleMessage(msg, (uint32_t)n, out, sizeof out);
    assert(n > 0 && out[8] == DOIP_NACK_UNKNOWN_PAYLOAD);

    printf("\nall assertions passed\n");
    return 0;
}
