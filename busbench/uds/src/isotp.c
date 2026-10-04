#include "isotp.h"
#include <string.h>

#define PCI_SF 0x00
#define PCI_FF 0x10
#define PCI_CF 0x20
#define PCI_FC 0x30

#define POLL_LIMIT 64      /* simulated bus is synchronous, so this only
                            * trips when the peer really said nothing */

static void send_flow_control(IsoTpSendFrame_t send)
{
    /* 0x30 = continue to send, block size 0 = no more flow control
     * needed, STmin 0 = no gap required between frames. */
    uint8_t fc[3] = { PCI_FC, 0x00, 0x00 };
    send(fc, 3);
}

int IsoTp_RxFeed(IsoTpRx_t *rx, const uint8_t *frame, uint8_t len, IsoTpSendFrame_t send)
{
    if (len < 1) return -1;
    uint8_t type = frame[0] & 0xF0;

    if (type == PCI_SF) {
        uint8_t n = frame[0] & 0x0F;
        if (n == 0 || n > 7 || n + 1 > len) return -1;
        memcpy(rx->buf, &frame[1], n);
        rx->active = false;
        rx->total = rx->got = n;
        return n;
    }

    if (type == PCI_FF) {
        if (len < 2) return -1;
        uint16_t total = (uint16_t)(((frame[0] & 0x0F) << 8) | frame[1]);
        if (total > ISOTP_MAX_PAYLOAD || total <= 7) return -1;
        uint8_t first = (len > 2) ? (uint8_t)(len - 2) : 0;
        memcpy(rx->buf, &frame[2], first);
        rx->total   = total;
        rx->got     = first;
        rx->next_sn = 1;
        rx->active  = true;
        if (send) send_flow_control(send);
        return 0;
    }

    if (type == PCI_CF) {
        if (!rx->active) return -1;
        /* A mismatched sequence number means a frame was lost. Better to
         * fail loudly than hand back a message with a hole in it. */
        if ((frame[0] & 0x0F) != rx->next_sn) return -1;
        rx->next_sn = (uint8_t)((rx->next_sn + 1) & 0x0F);

        uint16_t remaining = (uint16_t)(rx->total - rx->got);
        uint16_t chunk = (uint16_t)(len - 1);
        if (chunk > remaining) chunk = remaining;
        memcpy(&rx->buf[rx->got], &frame[1], chunk);
        rx->got = (uint16_t)(rx->got + chunk);

        if (rx->got >= rx->total) {
            rx->active = false;
            return rx->total;
        }
        return 0;
    }

    return 0;   /* flow control, handled by the transmit side */
}

bool IsoTp_TxStart(IsoTpTx_t *tx, const uint8_t *data, uint16_t len, IsoTpSendFrame_t send)
{
    memset(tx, 0, sizeof *tx);
    if (len == 0 || len > ISOTP_MAX_PAYLOAD) return true;

    if (len <= 7) {
        uint8_t f[8] = {0};
        f[0] = (uint8_t)(PCI_SF | len);
        memcpy(&f[1], data, len);
        send(f, (uint8_t)(len + 1));
        return true;
    }

    memcpy(tx->buf, data, len);
    tx->total  = len;
    tx->sent   = 6;
    tx->sn     = 1;
    tx->active = true;

    uint8_t f[8];
    f[0] = (uint8_t)(PCI_FF | ((len >> 8) & 0x0F));
    f[1] = (uint8_t)(len & 0xFF);
    memcpy(&f[2], data, 6);
    send(f, 8);
    return false;
}

void IsoTp_TxOnFlowControl(IsoTpTx_t *tx, IsoTpSendFrame_t send)
{
    if (!tx->active) return;

    while (tx->sent < tx->total) {
        uint8_t f[8] = {0};
        uint16_t chunk = (uint16_t)(tx->total - tx->sent);
        if (chunk > 7) chunk = 7;
        f[0] = (uint8_t)(PCI_CF | tx->sn);
        tx->sn = (uint8_t)((tx->sn + 1) & 0x0F);
        memcpy(&f[1], &tx->buf[tx->sent], chunk);
        tx->sent = (uint16_t)(tx->sent + chunk);
        send(f, (uint8_t)(chunk + 1));
    }
    tx->active = false;
}

int IsoTp_SendBlocking(const uint8_t *data, uint16_t len,
                       IsoTpSendFrame_t send, IsoTpRecvFrame_t recv)
{
    IsoTpTx_t tx;
    if (IsoTp_TxStart(&tx, data, len, send)) return 0;

    /* Long message: nothing more may go out until the peer grants it. */
    for (int i = 0; i < POLL_LIMIT; i++) {
        uint8_t f[8], n = 0;
        if (!recv(f, &n)) continue;
        if (n >= 1 && (f[0] & 0xF0) == PCI_FC) {
            if ((f[0] & 0x0F) == 0x02) return -1;    /* overflow, peer refused */
            IsoTp_TxOnFlowControl(&tx, send);
            return 0;
        }
    }
    return -1;
}

int IsoTp_RecvBlocking(uint8_t *out, uint16_t cap, IsoTpSendFrame_t send, IsoTpRecvFrame_t recv)
{
    IsoTpRx_t rx;
    memset(&rx, 0, sizeof rx);

    for (int i = 0; i < POLL_LIMIT; i++) {
        uint8_t f[8], n = 0;
        if (!recv(f, &n)) continue;

        int r = IsoTp_RxFeed(&rx, f, n, send);
        if (r < 0) return -1;
        if (r > 0) {
            if (r > cap) return -1;
            memcpy(out, rx.buf, (size_t)r);
            return r;
        }
    }
    return -1;   /* timeout */
}
