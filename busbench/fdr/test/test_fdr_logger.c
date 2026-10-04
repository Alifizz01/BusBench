#include "fdr_logger.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

#define STORE "fdr_store.bin"

static uint64_t fake_now;
static uint64_t fake_clock(void) { return fake_now += 1000; }   /* 1 ms per frame */

static uint64_t seen[64];
static uint8_t  seen_source[64];
static uint16_t seen_first[64];
static int      seen_count;

static void collect(const FdrFrame_t *f)
{
    seen[seen_count] = f->timestamp_us;
    seen_source[seen_count] = f->source;
    seen_first[seen_count] = (uint16_t)(f->payload[0] | (f->payload[1] << 8));
    seen_count++;
}

static void reset_seen(void) { seen_count = 0; }

static void append_u16(uint8_t source, uint16_t value)
{
    uint8_t payload[2] = { (uint8_t)value, (uint8_t)(value >> 8) };
    FdrLogger_Append(source, payload, 2);
}

int main(void)
{
    remove(STORE);
    fake_now = 0;
    FdrLogger_SetClock(fake_clock);

    /* Known good CRC-16/CCITT-FALSE vector, so the two implementations
     * cannot disagree about what a valid frame looks like. */
    assert(Fdr_Crc16((const uint8_t *)"123456789", 9) == 0x29B1);

    assert(FdrLogger_Init(STORE, 8));

    /* Frames from projects 1 and 6, which is the point of this one. */
    for (uint16_t i = 1; i <= 5; i++)
        append_u16(i % 2 ? FDR_SOURCE_CAN : FDR_SOURCE_ARINC, i);
    FdrLogger_Close();

    reset_seen();
    assert(FdrLogger_Replay(STORE, collect) == 5);
    assert(seen_count == 5);
    for (int i = 1; i < seen_count; i++) assert(seen[i] > seen[i - 1]);
    assert(seen_first[0] == 1 && seen_first[4] == 5);
    printf("5 frames written and replayed in order\n");

    /* Overrun the ring. The oldest go, the newest stay, and the replay is
     * still chronological even though the ring wrapped. */
    assert(FdrLogger_Init(STORE, 8));
    for (uint16_t i = 6; i <= 20; i++)
        append_u16(FDR_SOURCE_EVENT, i);
    FdrLogger_Close();

    reset_seen();
    assert(FdrLogger_Replay(STORE, collect) == 8);      /* capacity, not 20 */
    assert(seen_first[0] == 13 && seen_first[7] == 20); /* the most recent 8 */
    for (int i = 1; i < seen_count; i++) assert(seen[i] > seen[i - 1]);
    printf("ring wrapped: kept the newest 8 of 20, still in order\n");

    /* Reopening must resume after the newest frame, not stamp on it. */
    assert(FdrLogger_Init(STORE, 8));
    append_u16(FDR_SOURCE_EVENT, 21);
    FdrLogger_Close();
    reset_seen();
    assert(FdrLogger_Replay(STORE, collect) == 8);
    assert(seen_first[7] == 21 && seen_first[0] == 14);
    printf("reopened and continued without overwriting the newest frame\n");

    /* Corrupt one frame in the middle. Exactly one frame is lost. */
    FILE *f = fopen(STORE, "r+b");
    assert(f);
    fseek(f, 3 * FDR_FRAME_BYTES + 15, SEEK_SET);   /* inside slot 3's payload */
    fputc(0xFF, f);
    fclose(f);

    reset_seen();
    uint32_t good = FdrLogger_Replay(STORE, collect);
    assert(good == 7);
    assert(FdrLogger_LastReplayDiscarded() == 1);
    for (int i = 1; i < seen_count; i++) assert(seen[i] > seen[i - 1]);
    printf("one flipped byte cost exactly 1 frame, the other 7 survived\n");

    /* A torn write: the last frame was cut off mid record by the power
     * going away. It must be skipped, not misread. */
    remove(STORE);
    fake_now = 0;
    assert(FdrLogger_Init(STORE, 4));
    append_u16(FDR_SOURCE_CAN, 100);
    append_u16(FDR_SOURCE_CAN, 200);
    FdrLogger_Close();

    f = fopen(STORE, "r+b");
    assert(f);
    fseek(f, FDR_FRAME_BYTES, SEEK_SET);
    for (int i = 0; i < 10; i++) fputc(0xAB, f);     /* half a frame, then nothing */
    fclose(f);

    reset_seen();
    assert(FdrLogger_Replay(STORE, collect) == 1);
    assert(FdrLogger_LastReplayDiscarded() == 1);
    assert(seen_first[0] == 100);
    printf("torn final frame skipped, everything before it recovered\n");

    printf("\nall assertions passed\n");
    remove(STORE);
    return 0;
}
