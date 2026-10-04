#ifndef ISOTP_H
#define ISOTP_H
/* ISO-TP (ISO 15765-2): carries a UDS message of up to 4095 bytes over
 * CAN frames that only hold 8. Four frame types do the whole job:
 *
 *   Single Frame   0x0L                    payload fits in one frame
 *   First Frame    0x1L LL                 start of a long message
 *   Flow Control   0x30 BS STmin           receiver says "go ahead"
 *   Consecutive    0x2N                    N is a wrapping 1..15 counter
 *
 * The sequence number is the point of the protocol: it is how the
 * receiver notices a dropped frame instead of silently gluing together
 * a corrupt message. */

#include <stdint.h>
#include <stdbool.h>

#define ISOTP_MAX_PAYLOAD 512      /* the standard allows 4095, this is enough here */

typedef void (*IsoTpSendFrame_t)(const uint8_t *frame, uint8_t len);
typedef bool (*IsoTpRecvFrame_t)(uint8_t *frame, uint8_t *len);   /* false = nothing waiting */

/* Reassembly state for one direction. */
typedef struct {
    uint8_t  buf[ISOTP_MAX_PAYLOAD];
    uint16_t total;
    uint16_t got;
    uint8_t  next_sn;
    bool     active;
} IsoTpRx_t;

/* Transmit state, needed because a long message pauses until the peer
 * sends flow control. */
typedef struct {
    uint8_t  buf[ISOTP_MAX_PAYLOAD];
    uint16_t total;
    uint16_t sent;
    uint8_t  sn;
    bool     active;
} IsoTpTx_t;

/* Feed one received CAN frame.
 * Returns  >0 = a complete message of that length is in rx->buf
 *           0 = more frames needed
 *          -1 = protocol error (wrong sequence number, overflow). */
int  IsoTp_RxFeed(IsoTpRx_t *rx, const uint8_t *frame, uint8_t len, IsoTpSendFrame_t send);

/* Begins a transmission: sends a single frame, or a first frame and then
 * waits for flow control. Returns true if the message is already done. */
bool IsoTp_TxStart(IsoTpTx_t *tx, const uint8_t *data, uint16_t len, IsoTpSendFrame_t send);

/* Called when flow control arrives, sends the remaining consecutive frames. */
void IsoTp_TxOnFlowControl(IsoTpTx_t *tx, IsoTpSendFrame_t send);

/* Blocking helpers for the client side, which unlike an ECU is allowed
 * to sit and wait. Return 0 / message length, or -1 on error or timeout. */
int  IsoTp_SendBlocking(const uint8_t *data, uint16_t len,
                        IsoTpSendFrame_t send, IsoTpRecvFrame_t recv);
int  IsoTp_RecvBlocking(uint8_t *out, uint16_t cap,
                        IsoTpSendFrame_t send, IsoTpRecvFrame_t recv);

#endif /* ISOTP_H */
