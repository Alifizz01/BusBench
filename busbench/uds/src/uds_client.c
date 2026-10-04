/* The client side of UDS. Every service is the same three steps: build a
 * request, hand it to ISO-TP, then work out whether what came back is an
 * answer, a refusal, or the ECU asking for more time. */

#include "uds_client.h"
#include <string.h>

#define NRC_RESPONSE_PENDING 0x78
#define PENDING_LIMIT        16     /* an ECU may stall, but not forever */

static IsoTpSendFrame_t bus_send;
static IsoTpRecvFrame_t bus_recv;
static uint8_t last_nrc;

void Uds_SetTransport(IsoTpSendFrame_t send, IsoTpRecvFrame_t recv)
{
    bus_send = send;
    bus_recv = recv;
    last_nrc = 0;
}

uint8_t Uds_GetLastNrc(void) { return last_nrc; }

/* Sends one request and returns the positive response, or the reason
 * there is not one. */
static UdsResult_t transact(const uint8_t *req, uint16_t req_len,
                            uint8_t *resp, uint16_t resp_cap, uint16_t *resp_len)
{
    if (!bus_send || !bus_recv) return UDS_TX_ERROR;
    last_nrc = 0;

    if (IsoTp_SendBlocking(req, req_len, bus_send, bus_recv) != 0)
        return UDS_TX_ERROR;

    for (int attempt = 0; attempt < PENDING_LIMIT; attempt++) {
        int n = IsoTp_RecvBlocking(resp, resp_cap, bus_send, bus_recv);
        if (n < 0) return UDS_TIMEOUT;

        if (n >= 3 && resp[0] == 0x7F) {
            /* 0x78 is not a failure, it means "still working, keep
             * waiting". Treating it as an error is the classic mistake
             * that makes a tester look broken against a slow ECU. */
            if (resp[2] == NRC_RESPONSE_PENDING) continue;
            last_nrc = resp[2];
            return UDS_NEGATIVE_RESPONSE;
        }

        /* A positive response is always the request SID plus 0x40. */
        if (n >= 1 && resp[0] != (uint8_t)(req[0] + 0x40)) return UDS_TX_ERROR;

        if (resp_len) *resp_len = (uint16_t)n;
        return UDS_OK;
    }
    return UDS_TIMEOUT;
}

UdsResult_t Uds_StartSession(uint8_t session_type)
{
    uint8_t req[2] = { 0x10, session_type };
    uint8_t resp[16];
    return transact(req, 2, resp, sizeof resp, NULL);
}

UdsResult_t Uds_ReadDataByIdentifier(uint16_t did, uint8_t *out, uint16_t out_cap, uint16_t *out_len)
{
    uint8_t req[3] = { 0x22, (uint8_t)(did >> 8), (uint8_t)did };
    uint8_t resp[ISOTP_MAX_PAYLOAD];
    uint16_t n = 0;

    UdsResult_t r = transact(req, 3, resp, sizeof resp, &n);
    if (r != UDS_OK) return r;
    if (n < 3) return UDS_TX_ERROR;

    /* Guard against an ECU answering with a different identifier. */
    if (resp[1] != req[1] || resp[2] != req[2]) return UDS_TX_ERROR;

    uint16_t payload = (uint16_t)(n - 3);
    if (payload > out_cap) return UDS_TX_ERROR;
    memcpy(out, &resp[3], payload);
    if (out_len) *out_len = payload;
    return UDS_OK;
}

UdsResult_t Uds_RequestSeed(uint8_t level, uint8_t *seed_out, uint16_t cap, uint16_t *len_out)
{
    uint8_t req[2] = { 0x27, level };
    uint8_t resp[32];
    uint16_t n = 0;

    UdsResult_t r = transact(req, 2, resp, sizeof resp, &n);
    if (r != UDS_OK) return r;
    if (n < 2) return UDS_TX_ERROR;

    uint16_t seed_len = (uint16_t)(n - 2);
    if (seed_len > cap) return UDS_TX_ERROR;
    memcpy(seed_out, &resp[2], seed_len);
    if (len_out) *len_out = seed_len;
    return UDS_OK;
}

UdsResult_t Uds_SecurityAccess(uint8_t level, const uint8_t *key, uint16_t key_len)
{
    uint8_t req[ISOTP_MAX_PAYLOAD];
    uint8_t resp[32];
    if ((uint16_t)(key_len + 2) > sizeof req) return UDS_TX_ERROR;

    req[0] = 0x27;
    req[1] = level;
    memcpy(&req[2], key, key_len);
    return transact(req, (uint16_t)(key_len + 2), resp, sizeof resp, NULL);
}

UdsResult_t Uds_WriteDataByIdentifier(uint16_t did, const uint8_t *data, uint16_t len)
{
    uint8_t req[ISOTP_MAX_PAYLOAD];
    uint8_t resp[32];
    if ((uint16_t)(len + 3) > sizeof req) return UDS_TX_ERROR;

    req[0] = 0x2E;
    req[1] = (uint8_t)(did >> 8);
    req[2] = (uint8_t)did;
    memcpy(&req[3], data, len);
    return transact(req, (uint16_t)(len + 3), resp, sizeof resp, NULL);
}
