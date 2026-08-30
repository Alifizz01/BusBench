/* Crash survivable circular logger.
 *
 * Three decisions do all the work:
 *
 *   Fixed 32 byte frames. A slot index is a multiply, and a frame that
 *   was half written cannot shift everything after it.
 *
 *   Explicit serialisation, never fwrite of the struct. Struct padding
 *   and endianness differ between the recorder and whatever machine
 *   reads the store afterwards, which is exactly the machine that
 *   matters after an accident.
 *
 *   A CRC per frame, not per file. One torn frame costs you one frame.
 *   A whole-file checksum would cost you the entire recording. */

#include "fdr_logger.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

static FILE    *store;
static uint32_t capacity;
static uint32_t next_slot;
static uint64_t (*clock_fn)(void);
static uint32_t last_discarded;
static uint64_t builtin_counter;

uint16_t Fdr_Crc16(const uint8_t *data, size_t len)
{
    /* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection. */
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++)
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
    return crc;
}

static uint64_t builtin_clock(void)
{
    /* Wall clock seconds plus a counter, so timestamps stay strictly
     * increasing even when several frames land in the same second. */
    return (uint64_t)time(NULL) * 1000000ull + (++builtin_counter);
}

void FdrLogger_SetClock(uint64_t (*now_us)(void)) { clock_fn = now_us; }

uint32_t FdrLogger_LastReplayDiscarded(void) { return last_discarded; }

static void pack(uint8_t *out, const FdrFrame_t *f)
{
    memset(out, 0, FDR_FRAME_BYTES);
    for (int i = 0; i < 4; i++) out[i]     = (uint8_t)(f->magic >> (8 * i));
    for (int i = 0; i < 8; i++) out[4 + i] = (uint8_t)(f->timestamp_us >> (8 * i));
    out[12] = f->source;
    out[13] = f->payload_len;
    memcpy(&out[14], f->payload, FDR_PAYLOAD_MAX);

    uint16_t crc = Fdr_Crc16(out, 30);
    out[30] = (uint8_t)crc;
    out[31] = (uint8_t)(crc >> 8);
}

static bool unpack(const uint8_t *in, FdrFrame_t *f)
{
    f->magic = 0;
    for (int i = 0; i < 4; i++) f->magic |= (uint32_t)in[i] << (8 * i);
    /* The magic is what lets the decoder tell a written slot from an
     * empty one, and lets it resync after a run of corruption. */
    if (f->magic != FDR_MAGIC) return false;

    uint16_t stored = (uint16_t)(in[30] | ((uint16_t)in[31] << 8));
    if (stored != Fdr_Crc16(in, 30)) return false;

    f->timestamp_us = 0;
    for (int i = 0; i < 8; i++) f->timestamp_us |= (uint64_t)in[4 + i] << (8 * i);
    f->source      = in[12];
    f->payload_len = in[13];
    if (f->payload_len > FDR_PAYLOAD_MAX) return false;
    memcpy(f->payload, &in[14], FDR_PAYLOAD_MAX);
    f->crc16 = stored;
    return true;
}

bool FdrLogger_Init(const char *path, uint32_t capacity_frames)
{
    FdrLogger_Close();
    if (capacity_frames == 0) return false;
    capacity = capacity_frames;
    builtin_counter = 0;

    /* Open for update, creating the file if this is the first flight. */
    store = fopen(path, "r+b");
    if (!store) {
        store = fopen(path, "w+b");
        if (!store) return false;
    }

    /* A real FDR has a hard, certified, fixed capacity. Size the store
     * once and never grow it, so a full disk can never be the reason a
     * recording stops. */
    uint8_t empty[FDR_FRAME_BYTES];
    memset(empty, 0, sizeof empty);
    fseek(store, 0, SEEK_END);
    long size = ftell(store);
    for (long slot = size / FDR_FRAME_BYTES; slot < (long)capacity; slot++)
        fwrite(empty, 1, FDR_FRAME_BYTES, store);
    fflush(store);

    /* Resume where the last flight stopped: the slot after the newest
     * valid frame. Without this, a power cycle would overwrite the most
     * recent data first, which is the data anyone actually wants. */
    next_slot = 0;
    uint64_t newest = 0;
    uint8_t raw[FDR_FRAME_BYTES];
    FdrFrame_t frame;

    for (uint32_t slot = 0; slot < capacity; slot++) {
        fseek(store, (long)slot * FDR_FRAME_BYTES, SEEK_SET);
        if (fread(raw, 1, FDR_FRAME_BYTES, store) != FDR_FRAME_BYTES) break;
        if (!unpack(raw, &frame)) continue;
        if (frame.timestamp_us >= newest) {
            newest = frame.timestamp_us;
            next_slot = (slot + 1) % capacity;
        }
    }

    return true;
}

void FdrLogger_Append(uint8_t source, const uint8_t *payload, uint8_t len)
{
    if (!store) return;
    if (len > FDR_PAYLOAD_MAX) len = FDR_PAYLOAD_MAX;

    FdrFrame_t f;
    memset(&f, 0, sizeof f);
    f.magic        = FDR_MAGIC;
    f.timestamp_us = clock_fn ? clock_fn() : builtin_clock();
    f.source       = source;
    f.payload_len  = len;
    if (payload && len) memcpy(f.payload, payload, len);

    uint8_t raw[FDR_FRAME_BYTES];
    pack(raw, &f);

    fseek(store, (long)next_slot * FDR_FRAME_BYTES, SEEK_SET);
    fwrite(raw, 1, FDR_FRAME_BYTES, store);
    /* Flushed on every append. Buffering would trade the last few seconds
     * of the recording for throughput, and the last few seconds are the
     * entire reason the box exists. */
    fflush(store);

    /* When full, overwrite the oldest. An FDR keeps the most recent N
     * hours; it never stops recording because it filled up. */
    next_slot = (next_slot + 1) % capacity;
}

void FdrLogger_Close(void)
{
    if (store) { fclose(store); store = NULL; }
}

static int by_timestamp(const void *a, const void *b)
{
    uint64_t ta = ((const FdrFrame_t *)a)->timestamp_us;
    uint64_t tb = ((const FdrFrame_t *)b)->timestamp_us;
    return (ta < tb) ? -1 : (ta > tb) ? 1 : 0;
}

uint32_t FdrLogger_Replay(const char *path, void (*on_frame)(const FdrFrame_t *))
{
    last_discarded = 0;

    FILE *f = fopen(path, "rb");
    if (!f) return 0;

    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    uint32_t slots = (uint32_t)(size / FDR_FRAME_BYTES);
    FdrFrame_t *frames = malloc((size_t)slots * sizeof(FdrFrame_t));
    if (!frames) { fclose(f); return 0; }

    uint32_t good = 0;
    uint8_t raw[FDR_FRAME_BYTES];

    for (uint32_t slot = 0; slot < slots; slot++) {
        if (fread(raw, 1, FDR_FRAME_BYTES, f) != FDR_FRAME_BYTES) break;

        /* An all zero slot was simply never written. A slot with the
         * magic but a bad CRC is a torn write, and that is worth
         * counting: a silently shorter timeline is the worst outcome. */
        bool blank = true;
        for (int i = 0; i < FDR_FRAME_BYTES && blank; i++) if (raw[i]) blank = false;
        if (blank) continue;

        if (unpack(raw, &frames[good])) good++;
        else last_discarded++;
    }
    fclose(f);

    /* The ring wraps, so slot order is not time order. */
    qsort(frames, good, sizeof(FdrFrame_t), by_timestamp);

    if (on_frame)
        for (uint32_t i = 0; i < good; i++) on_frame(&frames[i]);

    free(frames);
    return good;
}
