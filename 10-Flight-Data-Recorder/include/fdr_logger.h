#ifndef FDR_LOGGER_H
#define FDR_LOGGER_H
/* Project 10: Flight Data Recorder ("black box") style logger.
 * Goal: a crash-survivable circular logger - fixed-size ring buffer in
 * non-volatile storage, append-only, self-describing frame format, and
 * a decoder tool that can reconstruct the timeline even if writing was
 * interrupted mid-frame (power loss during a crash is the exact
 * scenario this format must survive). Ties together everything from
 * projects 1-9: it logs decoded CAN signals AND ARINC429 words. */

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define FDR_MAGIC        0x46445231u   /* "FDR1" */
#define FDR_PAYLOAD_MAX  16
#define FDR_FRAME_BYTES  32            /* fixed on disk, so a slot index is
                                        * just a multiply, and a torn frame
                                        * cannot shift everything after it */

/* Sources, so the decoder knows what the payload means. */
#define FDR_SOURCE_CAN     0
#define FDR_SOURCE_ARINC   1
#define FDR_SOURCE_EVENT   2

typedef struct {
    uint32_t magic;          /* frame sync pattern, lets the decoder resync after corruption */
    uint64_t timestamp_us;
    uint8_t  source;          /* 0 = CAN signal, 1 = ARINC429 word, 2 = internal event */
    uint8_t  payload_len;
    uint8_t  payload[16];
    uint16_t crc16;            /* covers this frame only - one bad frame never breaks the rest */
} FdrFrame_t;

/* Initializes the circular buffer over a fixed non-volatile region
 * (simulated as a file on a PC build). Never grows - a real FDR has a
 * hard, certified, fixed capacity (commonly last 25 hours of data). */
bool FdrLogger_Init(const char *backing_store_path, uint32_t capacity_frames);

/* Appends one frame; when full, silently overwrites the OLDEST frame -
 * FDRs always keep "the most recent N hours", never stop-when-full. */
void FdrLogger_Append(uint8_t source, const uint8_t *payload, uint8_t len);

/* Decoder-side: replays every valid frame in chronological order,
 * skipping/logging any frame whose CRC doesn't match (torn write). */
uint32_t FdrLogger_Replay(const char *backing_store_path,
                           void (*on_frame)(const FdrFrame_t *frame));

/* added: the clock is injectable so a test can produce a known timeline.
 * Pass NULL to go back to the built in one. */
void FdrLogger_SetClock(uint64_t (*now_us)(void));

/* added: closes the backing store. Every append is flushed as it happens,
 * so nothing is lost if this is never reached, which is the point. */
void FdrLogger_Close(void);

/* added: how many frames were discarded by the last replay, so a corrupt
 * store is a number rather than a silently shorter timeline. */
uint32_t FdrLogger_LastReplayDiscarded(void);

/* added: CRC-16/CCITT-FALSE, exposed because the decoder is a separate
 * tool in real life and has to compute the identical value. */
uint16_t Fdr_Crc16(const uint8_t *data, size_t len);

#endif /* FDR_LOGGER_H */
