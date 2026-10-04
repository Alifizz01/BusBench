/* Walks the full diagnostic session the way a scan tool does, and checks
 * the refusals as carefully as the successes. An ECU that says yes to
 * everything is the bug. */

#include "uds_client.h"
#include "ecu_sim.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

static uint32_t key_from_seed(uint32_t s)
{
    return (s ^ 0x5A5A5A5Au) + 0x11223344u;
}

int main(void)
{
    EcuSim_Reset();
    Uds_SetTransport(EcuSim_ClientSend, EcuSim_ClientRecv);

    uint8_t buf[64];
    uint16_t len = 0;

    /* Default session: reading is allowed. */
    assert(Uds_StartSession(0x01) == UDS_OK);

    /* 20 byte response, so ISO-TP has to segment it and reassemble it. */
    assert(Uds_ReadDataByIdentifier(0xF190, buf, sizeof buf, &len) == UDS_OK);
    assert(len == 17);
    assert(memcmp(buf, "WVWZZZ1JZ3W386752", 17) == 0);
    printf("VIN            %.17s\n", buf);

    assert(Uds_ReadDataByIdentifier(0xF195, buf, sizeof buf, &len) == UDS_OK);
    printf("SW version     %.*s\n", len, buf);

    /* This one answers 0x78 first. The client must keep waiting. */
    assert(Uds_ReadDataByIdentifier(0x0110, buf, sizeof buf, &len) == UDS_OK);
    assert(len == 2 && buf[0] == 0x0F && buf[1] == 0xA0);
    printf("Engine speed   %u raw (after a responsePending)\n", (buf[0] << 8) | buf[1]);

    /* An identifier the ECU does not have is a refusal, not a timeout. */
    assert(Uds_ReadDataByIdentifier(0xDEAD, buf, sizeof buf, &len) == UDS_NEGATIVE_RESPONSE);
    assert(Uds_GetLastNrc() == 0x31);      /* requestOutOfRange */

    /* Security is not even offered in the default session. */
    assert(Uds_RequestSeed(0x01, buf, sizeof buf, &len) == UDS_NEGATIVE_RESPONSE);
    assert(Uds_GetLastNrc() == 0x7F);      /* serviceNotSupportedInActiveSession */

    assert(Uds_StartSession(0x03) == UDS_OK);

    /* Writing is refused while locked. This is the check that matters. */
    uint8_t payload[2] = { 0x12, 0x34 };
    assert(Uds_WriteDataByIdentifier(0xF199, payload, 2) == UDS_NEGATIVE_RESPONSE);
    assert(Uds_GetLastNrc() == 0x33);      /* securityAccessDenied */

    /* A wrong key must not unlock anything. */
    uint8_t bad[4] = { 0, 0, 0, 0 };
    assert(Uds_RequestSeed(0x01, buf, sizeof buf, &len) == UDS_OK && len == 4);
    assert(Uds_SecurityAccess(0x02, bad, 4) == UDS_NEGATIVE_RESPONSE);
    assert(Uds_GetLastNrc() == 0x35);      /* invalidKey */
    assert(!EcuSim_IsUnlocked());

    /* Now the real handshake: seed in, key out, level+1 to send it. */
    assert(Uds_RequestSeed(0x01, buf, sizeof buf, &len) == UDS_OK && len == 4);
    uint32_t seed = ((uint32_t)buf[0] << 24) | ((uint32_t)buf[1] << 16) |
                    ((uint32_t)buf[2] << 8)  |  (uint32_t)buf[3];
    uint32_t key = key_from_seed(seed);
    uint8_t key_bytes[4] = { (uint8_t)(key >> 24), (uint8_t)(key >> 16),
                             (uint8_t)(key >> 8),  (uint8_t)key };
    assert(Uds_SecurityAccess(0x02, key_bytes, 4) == UDS_OK);
    assert(EcuSim_IsUnlocked());
    printf("seed 0x%08X -> key 0x%08X, unlocked\n", seed, key);

    assert(Uds_WriteDataByIdentifier(0xF199, payload, 2) == UDS_OK);

    /* Dropping back to the default session relocks it. */
    assert(Uds_StartSession(0x01) == UDS_OK);
    assert(!EcuSim_IsUnlocked());
    assert(Uds_WriteDataByIdentifier(0xF199, payload, 2) == UDS_NEGATIVE_RESPONSE);

    /* A long request has to segment outbound too, not just inbound. */
    assert(Uds_StartSession(0x03) == UDS_OK);
    uint8_t big[40];
    memset(big, 0xAB, sizeof big);
    assert(Uds_WriteDataByIdentifier(0xF199, big, sizeof big) == UDS_NEGATIVE_RESPONSE);
    assert(Uds_GetLastNrc() == 0x33);      /* refused, but it arrived intact */

    printf("\nall assertions passed\n");
    return 0;
}
