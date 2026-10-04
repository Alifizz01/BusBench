#include "mil1553_bc.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

int main(void)
{
    Mil1553CommandWord_t cmd, back;
    Mil1553StatusWord_t status;
    uint16_t data[32];

    /* Command word round trip. */
    cmd = (Mil1553CommandWord_t){ .rt_address = 5, .tr = 1, .subaddress = 9, .word_count = 4 };
    uint16_t raw = Mil1553_EncodeCommand(&cmd);
    assert(raw == ((5u << 11) | (1u << 10) | (9u << 5) | 4u));
    Mil1553_DecodeCommand(raw, &back);
    assert(back.rt_address == 5 && back.tr == 1 && back.subaddress == 9 && back.word_count == 4);

    /* Word count 32 goes on the wire as 0, because five bits have to
     * cover a count that runs 1 to 32. */
    cmd.word_count = 32;
    raw = Mil1553_EncodeCommand(&cmd);
    assert((raw & 0x1F) == 0);
    Mil1553_DecodeCommand(raw, &back);
    assert(back.word_count == 32);
    printf("word count 32 encodes as 0 and decodes back to 32\n");

    /* On subaddress 0 or 31 those same five bits are a mode code, so
     * they must NOT become a word count of 32. */
    cmd = (Mil1553CommandWord_t){ .rt_address = 5, .tr = 1, .subaddress = 0,
                                  .word_count = MIL1553_MODE_TRANSMIT_STATUS };
    Mil1553_DecodeCommand(Mil1553_EncodeCommand(&cmd), &back);
    assert(back.word_count == MIL1553_MODE_TRANSMIT_STATUS);
    cmd.word_count = 0;
    Mil1553_DecodeCommand(Mil1553_EncodeCommand(&cmd), &back);
    assert(back.word_count == 0);      /* mode code 0, not a count of 32 */
    printf("subaddress 0 keeps its mode code instead of becoming a count\n");

    Rt_Reset();
    Mil1553_ResetStats();
    Rt_Connect(3);
    Rt_Connect(5);

    /* BC to RT, then read it back the other way. */
    uint16_t payload[4] = { 0x1111, 0x2222, 0x3333, 0x4444 };
    cmd = (Mil1553CommandWord_t){ .rt_address = 3, .tr = 0, .subaddress = 1, .word_count = 4 };
    memcpy(data, payload, sizeof payload);
    assert(Mil1553_BcTransaction(&cmd, data, 4, &status));

    cmd.tr = 1;
    memset(data, 0, sizeof data);
    assert(Mil1553_BcTransaction(&cmd, data, 32, &status));
    assert(memcmp(data, payload, sizeof payload) == 0);
    printf("BC wrote 4 words to RT 3 and read the same 4 back\n");

    /* No RT at that address means silence, and silence is a timeout.
     * There is no negative acknowledge on 1553. */
    cmd.rt_address = 12;
    assert(!Mil1553_BcTransaction(&cmd, data, 32, &status));
    printf("polling an absent RT times out\n");

    /* A busy RT answers, but with no data. Using the buffer anyway is
     * the bug this flag exists to prevent. */
    Rt_SetBusy(5, true);
    cmd.rt_address = 5;
    assert(!Mil1553_BcTransaction(&cmd, data, 32, &status));
    assert(status.busy && (status.status_flags & MIL1553_STATUS_BUSY));
    Rt_SetBusy(5, false);
    printf("busy RT reports busy instead of handing over stale data\n");

    /* A subsystem fault means the transfer worked but the data is not
     * trustworthy. Delivering it without the flag is how bad data
     * reaches a control law. */
    Rt_LoadSubaddress(5, 2, payload, 4);
    Rt_SetSubsystemFault(5, true);
    cmd = (Mil1553CommandWord_t){ .rt_address = 5, .tr = 1, .subaddress = 2, .word_count = 4 };
    assert(!Mil1553_BcTransaction(&cmd, data, 32, &status));
    assert(status.status_flags & MIL1553_STATUS_SUBSYSTEM_FLAG);

    /* The reset mode code clears it. */
    cmd = (Mil1553CommandWord_t){ .rt_address = 5, .tr = 0, .subaddress = 0,
                                  .word_count = MIL1553_MODE_RESET_RT };
    assert(Mil1553_BcTransaction(&cmd, NULL, 0, &status));
    cmd = (Mil1553CommandWord_t){ .rt_address = 5, .tr = 1, .subaddress = 2, .word_count = 4 };
    assert(Mil1553_BcTransaction(&cmd, data, 32, &status));
    printf("subsystem fault flagged, then cleared by the reset mode code\n");

    /* Broadcast: every RT takes the data and none of them answers. */
    cmd = (Mil1553CommandWord_t){ .rt_address = MIL1553_BROADCAST_ADDRESS,
                                  .tr = 0, .subaddress = 7, .word_count = 4 };
    memcpy(data, payload, sizeof payload);
    assert(Mil1553_BcTransaction(&cmd, data, 4, &status));
    assert(Rt_BroadcastCount(3) == 1 && Rt_BroadcastCount(5) == 1);

    uint16_t readback[4] = {0};
    assert(Rt_ReadSubaddress(3, 7, readback, 4) == 4);
    assert(memcmp(readback, payload, sizeof payload) == 0);
    printf("broadcast reached every RT, with no status word from any of them\n");

    /* The schedule. RT 9 is not on the bus, so it costs a retry and a
     * failure but must not stop the frame. */
    Rt_Reset();
    Mil1553_ResetStats();
    Rt_Connect(3);
    Rt_Connect(5);
    Rt_LoadSubaddress(3, 1, payload, 4);
    Rt_LoadSubaddress(5, 1, payload, 2);

    Mil1553CommandWord_t schedule[] = {
        { .rt_address = 3, .tr = 1, .subaddress = 1, .word_count = 4 },
        { .rt_address = 9, .tr = 1, .subaddress = 1, .word_count = 4 },   /* absent */
        { .rt_address = 5, .tr = 1, .subaddress = 1, .word_count = 2 },
    };
    Mil1553_RunSchedule(schedule, 3, 20);

    Mil1553Stats_t s;
    Mil1553_GetStats(&s);
    assert(s.transactions == 4);     /* three plus one retry */
    assert(s.retries == 1);
    assert(s.failures == 2);         /* the absent RT, twice */
    printf("frame ran all 3 slots despite one dead RT: %u transactions, "
           "%u retries, %u failures\n", s.transactions, s.retries, s.failures);

    printf("\nall assertions passed\n");
    return 0;
}
