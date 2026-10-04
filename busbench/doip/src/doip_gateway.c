/* DoIP protocol logic, deliberately free of sockets.
 *
 * Splitting the framing from the transport is what makes this testable:
 * every case below (bad version, lying length, diagnostics before
 * routing activation) is a plain buffer in and a plain buffer out. The
 * socket server in doip_server.c is then a thin loop around it. */

#include "doip_gateway.h"
#include <string.h>

#define MAX_PAYLOAD 4096

static bool routing_active;
static uint16_t active_tester;
static DoipUdsHandler_t uds_handler;

void DoipGateway_SetUdsHandler(DoipUdsHandler_t fn) { uds_handler = fn; }
bool DoipGateway_IsRoutingActive(void) { return routing_active; }

void DoipGateway_ResetSession(void)
{
    routing_active = false;
    active_tester = 0;
}

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }
static uint16_t get16(const uint8_t *p) { return (uint16_t)((p[0] << 8) | p[1]); }

int Doip_Build(uint16_t payload_type, const uint8_t *payload, uint32_t payload_len,
               uint8_t *out, uint32_t out_cap)
{
    if (out_cap < DOIP_HEADER_LEN + payload_len) return -1;

    out[0] = DOIP_VERSION;
    out[1] = (uint8_t)~DOIP_VERSION;
    put16(&out[2], payload_type);
    out[4] = (uint8_t)(payload_len >> 24);
    out[5] = (uint8_t)(payload_len >> 16);
    out[6] = (uint8_t)(payload_len >> 8);
    out[7] = (uint8_t)payload_len;
    if (payload_len) memcpy(&out[DOIP_HEADER_LEN], payload, payload_len);

    return (int)(DOIP_HEADER_LEN + payload_len);
}

int Doip_ParseHeader(const uint8_t *in, uint32_t in_len,
                     uint16_t *type_out, uint32_t *payload_len_out)
{
    if (in_len < DOIP_HEADER_LEN) return -1;

    /* Byte 1 must be the complement of byte 0. Cheap, and it catches a
     * stream that is not DoIP at all before anything else is believed. */
    if (in[1] != (uint8_t)~in[0]) return -1;
    if (in[0] != DOIP_VERSION) return -1;

    *type_out = get16(&in[2]);
    *payload_len_out = ((uint32_t)in[4] << 24) | ((uint32_t)in[5] << 16) |
                       ((uint32_t)in[6] << 8)  |  (uint32_t)in[7];
    return DOIP_HEADER_LEN;
}

static int generic_nack(uint8_t code, uint8_t *out, uint32_t out_cap)
{
    return Doip_Build(DOIP_GENERIC_NACK, &code, 1, out, out_cap);
}

int DoipGateway_HandleMessage(const uint8_t *in, uint32_t in_len,
                              uint8_t *out, uint32_t out_cap)
{
    uint16_t type;
    uint32_t payload_len;

    if (Doip_ParseHeader(in, in_len, &type, &payload_len) < 0)
        return generic_nack(DOIP_NACK_INCORRECT_PATTERN, out, out_cap);

    if (payload_len > MAX_PAYLOAD)
        return generic_nack(DOIP_NACK_MESSAGE_TOO_LARGE, out, out_cap);

    /* A header that claims more bytes than arrived is the classic way to
     * walk a parser off the end of its buffer. Length is checked against
     * what is actually here, never trusted on its own. */
    if (in_len < DOIP_HEADER_LEN + payload_len)
        return generic_nack(DOIP_NACK_INVALID_LENGTH, out, out_cap);

    const uint8_t *payload = &in[DOIP_HEADER_LEN];

    switch (type) {

    case DOIP_VEHICLE_IDENT_REQ: {
        /* Answered before routing activation on purpose: this is how a
         * tester discovers what it is plugged into. */
        uint8_t resp[33];
        memcpy(&resp[0], "WVWZZZ1JZ3W386752", 17);   /* VIN */
        put16(&resp[17], DOIP_ENTITY_ADDRESS);       /* logical address */
        memset(&resp[19], 0xAA, 6);                  /* EID, normally the MAC */
        memset(&resp[25], 0xBB, 6);                  /* GID, the group id */
        resp[31] = 0x00;                             /* no further action needed */
        return Doip_Build(DOIP_VEHICLE_IDENT_RESP, resp, 32, out, out_cap);
    }

    case DOIP_ROUTING_ACTIVATION_REQ: {
        if (payload_len < 7) return generic_nack(DOIP_NACK_INVALID_LENGTH, out, out_cap);

        uint16_t tester = get16(&payload[0]);
        uint8_t resp[9];
        put16(&resp[0], tester);
        put16(&resp[2], DOIP_ENTITY_ADDRESS);

        /* Address 0x0000 is not a tester. Accepting anything that asks is
         * how a gateway ends up talking to whatever is on the network. */
        if (tester == 0x0000) {
            resp[4] = DOIP_ROUTING_UNKNOWN_SOURCE;
        } else {
            resp[4] = DOIP_ROUTING_SUCCESS;
            routing_active = true;
            active_tester = tester;
        }
        memset(&resp[5], 0, 4);                      /* reserved by ISO */
        return Doip_Build(DOIP_ROUTING_ACTIVATION_RESP, resp, 9, out, out_cap);
    }

    case DOIP_DIAG_MESSAGE: {
        if (payload_len < 5) return generic_nack(DOIP_NACK_INVALID_LENGTH, out, out_cap);

        uint16_t source = get16(&payload[0]);
        uint16_t target = get16(&payload[2]);

        /* This is the check the whole state machine exists for. Without
         * it, anyone who can reach port 13400 can talk UDS to the car. */
        if (!routing_active || source != active_tester) {
            uint8_t nack[5];
            put16(&nack[0], target);
            put16(&nack[2], source);
            nack[4] = DOIP_DIAG_NACK_UNKNOWN_TARGET;
            return Doip_Build(DOIP_DIAG_NACK, nack, 5, out, out_cap);
        }

        if (target != DOIP_ENTITY_ADDRESS) {
            uint8_t nack[5];
            put16(&nack[0], target);
            put16(&nack[2], source);
            nack[4] = DOIP_DIAG_NACK_UNKNOWN_TARGET;
            return Doip_Build(DOIP_DIAG_NACK, nack, 5, out, out_cap);
        }

        /* Hand the UDS bytes to the CAN side and wrap whatever comes back.
         * The gateway itself understands none of it, which is the point:
         * adding a UDS service must not require touching this file. */
        uint8_t uds_resp[MAX_PAYLOAD];
        uint16_t uds_len = 0;
        if (uds_handler)
            uds_handler(&payload[4], (uint16_t)(payload_len - 4),
                        uds_resp, sizeof uds_resp, &uds_len);
        if (uds_len == 0) return -1;                 /* nothing to send back */

        uint8_t resp[MAX_PAYLOAD];
        put16(&resp[0], DOIP_ENTITY_ADDRESS);        /* now the source */
        put16(&resp[2], source);                     /* back to the tester */
        memcpy(&resp[4], uds_resp, uds_len);
        return Doip_Build(DOIP_DIAG_MESSAGE, resp, (uint32_t)(uds_len + 4), out, out_cap);
    }

    default:
        return generic_nack(DOIP_NACK_UNKNOWN_PAYLOAD, out, out_cap);
    }
}
