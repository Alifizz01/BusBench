#include "ecu_sim.h"
#include "isotp.h"
#include <string.h>

#define NRC_SERVICE_NOT_SUPPORTED       0x11
#define NRC_SUBFUNCTION_NOT_SUPPORTED   0x12
#define NRC_REQUEST_OUT_OF_RANGE        0x31
#define NRC_SECURITY_ACCESS_DENIED      0x33
#define NRC_INVALID_KEY                 0x35
#define NRC_RESPONSE_PENDING            0x78
#define NRC_WRONG_SESSION               0x7F

#define QUEUE_FRAMES 64

typedef struct { uint8_t data[8]; uint8_t len; } BusFrame_t;

static BusFrame_t q[QUEUE_FRAMES];
static int q_head, q_tail;

static IsoTpRx_t rx;
static IsoTpTx_t tx;

static uint8_t  session = 0x01;      /* 0x01 default, 0x03 extended */
static bool     unlocked;
static uint32_t seed;
static uint32_t rng = 0xACE1u;
static uint8_t  written_did_value[8];

/* Stand-in for the manufacturer's secret seed/key algorithm. A real one
 * lives in an HSM and is not in the repository, but the handshake shape
 * is identical. */
static uint32_t key_from_seed(uint32_t s)
{
    return (s ^ 0x5A5A5A5Au) + 0x11223344u;
}

static void push(const uint8_t *frame, uint8_t len)
{
    int next = (q_tail + 1) % QUEUE_FRAMES;
    if (next == q_head) return;              /* queue full, drop like a real bus would */
    memcpy(q[q_tail].data, frame, len);
    q[q_tail].len = len;
    q_tail = next;
}

void EcuSim_Reset(void)
{
    q_head = q_tail = 0;
    memset(&rx, 0, sizeof rx);
    memset(&tx, 0, sizeof tx);
    session  = 0x01;
    unlocked = false;
    seed     = 0;
    rng      = 0xACE1u;
}

bool EcuSim_IsUnlocked(void) { return unlocked; }

bool EcuSim_ClientRecv(uint8_t *frame, uint8_t *len)
{
    if (q_head == q_tail) return false;
    memcpy(frame, q[q_head].data, q[q_head].len);
    *len = q[q_head].len;
    q_head = (q_head + 1) % QUEUE_FRAMES;
    return true;
}

static void respond(const uint8_t *payload, uint16_t len)
{
    IsoTp_TxStart(&tx, payload, len, push);
}

static void negative(uint8_t sid, uint8_t nrc)
{
    uint8_t r[3] = { 0x7F, sid, nrc };
    respond(r, 3);
}

static void handle_request(const uint8_t *req, uint16_t len)
{
    if (len < 1) return;
    uint8_t sid = req[0];

    switch (sid) {

    case 0x10:   /* DiagnosticSessionControl */
        if (len < 2) { negative(sid, NRC_SUBFUNCTION_NOT_SUPPORTED); return; }
        if (req[1] != 0x01 && req[1] != 0x03) { negative(sid, NRC_SUBFUNCTION_NOT_SUPPORTED); return; }
        session = req[1];
        if (session == 0x01) unlocked = false;   /* dropping session relocks */
        {   /* echo the session plus the P2 timing the tester must honour */
            uint8_t r[6] = { 0x50, req[1], 0x00, 0x32, 0x01, 0xF4 };
            respond(r, 6);
        }
        return;

    case 0x22: { /* ReadDataByIdentifier */
        if (len < 3) { negative(sid, NRC_REQUEST_OUT_OF_RANGE); return; }
        uint16_t did = (uint16_t)((req[1] << 8) | req[2]);
        uint8_t r[32] = { 0x62, req[1], req[2] };

        if (did == 0xF190) {                       /* VIN, 17 bytes, forces segmentation */
            memcpy(&r[3], "WVWZZZ1JZ3W386752", 17);
            respond(r, 20);
        } else if (did == 0xF195) {                /* software version */
            memcpy(&r[3], "1.4.2", 5);
            respond(r, 8);
        } else if (did == 0x0110) {                /* a live measurement */
            /* Real ECUs stall here, so this one does too: the tester has
             * to keep waiting while 0x78 keeps arriving. */
            uint8_t pending[3] = { 0x7F, 0x22, NRC_RESPONSE_PENDING };
            respond(pending, 3);
            r[3] = 0x0F; r[4] = 0xA0;              /* 4000 raw */
            respond(r, 5);
        } else {
            negative(sid, NRC_REQUEST_OUT_OF_RANGE);
        }
        return;
    }

    case 0x27: { /* SecurityAccess */
        if (len < 2) { negative(sid, NRC_SUBFUNCTION_NOT_SUPPORTED); return; }
        if (session != 0x03) { negative(sid, NRC_WRONG_SESSION); return; }

        if (req[1] == 0x01) {                      /* requestSeed */
            rng = rng * 1103515245u + 12345u;      /* deterministic, still varies */
            seed = rng;
            uint8_t r[6] = { 0x67, 0x01,
                             (uint8_t)(seed >> 24), (uint8_t)(seed >> 16),
                             (uint8_t)(seed >> 8),  (uint8_t)seed };
            respond(r, 6);
        } else if (req[1] == 0x02) {               /* sendKey */
            if (len < 6) { negative(sid, NRC_INVALID_KEY); return; }
            uint32_t got = ((uint32_t)req[2] << 24) | ((uint32_t)req[3] << 16) |
                           ((uint32_t)req[4] << 8)  |  (uint32_t)req[5];
            if (got != key_from_seed(seed)) { negative(sid, NRC_INVALID_KEY); return; }
            unlocked = true;
            uint8_t r[2] = { 0x67, 0x02 };
            respond(r, 2);
        } else {
            negative(sid, NRC_SUBFUNCTION_NOT_SUPPORTED);
        }
        return;
    }

    case 0x2E: { /* WriteDataByIdentifier, the reason security exists */
        if (!unlocked) { negative(sid, NRC_SECURITY_ACCESS_DENIED); return; }
        if (len < 4) { negative(sid, NRC_REQUEST_OUT_OF_RANGE); return; }
        uint16_t n = (uint16_t)(len - 3);
        if (n > sizeof written_did_value) n = sizeof written_did_value;
        memcpy(written_did_value, &req[3], n);
        uint8_t r[3] = { 0x6E, req[1], req[2] };
        respond(r, 3);
        return;
    }

    default:
        negative(sid, NRC_SERVICE_NOT_SUPPORTED);
        return;
    }
}

void EcuSim_ClientSend(const uint8_t *frame, uint8_t len)
{
    if (len < 1) return;

    /* Flow control belongs to a transmission already in progress. */
    if ((frame[0] & 0xF0) == 0x30) {
        IsoTp_TxOnFlowControl(&tx, push);
        return;
    }

    int r = IsoTp_RxFeed(&rx, frame, len, push);
    if (r > 0) handle_request(rx.buf, (uint16_t)r);
}
