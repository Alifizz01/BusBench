/* MIL-STD-1553 bus controller, plus the simulated remote terminals it
 * polls. Two clearly separate halves in one file: the BC below the
 * "bus controller" banner, the RTs above it.
 *
 * The character of 1553 is that nothing happens unless the BC asks for
 * it. There is no arbitration and no RT ever speaks first, which is
 * exactly why it is used where timing has to be provable. */

#include "mil1553_bc.h"
#include <string.h>

/* ------------------------------------------------------------------ */
/* remote terminals                                                     */
/* ------------------------------------------------------------------ */

#define RT_COUNT      32
#define SUBADDRESSES  32
#define MAX_WORDS     32

typedef struct {
    bool     connected;
    bool     busy;
    bool     subsystem_fault;
    uint16_t data[SUBADDRESSES][MAX_WORDS];
    uint8_t  counts[SUBADDRESSES];
    uint32_t broadcasts_received;
} Rt_t;

static Rt_t rts[RT_COUNT];

void Rt_Reset(void) { memset(rts, 0, sizeof rts); }

void Rt_Connect(uint8_t a)    { if (a < RT_COUNT) rts[a].connected = true; }
void Rt_Disconnect(uint8_t a) { if (a < RT_COUNT) rts[a].connected = false; }

void Rt_SetBusy(uint8_t a, bool busy) { if (a < RT_COUNT) rts[a].busy = busy; }
void Rt_SetSubsystemFault(uint8_t a, bool f) { if (a < RT_COUNT) rts[a].subsystem_fault = f; }

void Rt_LoadSubaddress(uint8_t a, uint8_t sa, const uint16_t *words, uint8_t count)
{
    if (a >= RT_COUNT || sa >= SUBADDRESSES) return;
    if (count > MAX_WORDS) count = MAX_WORDS;
    memcpy(rts[a].data[sa], words, (size_t)count * sizeof(uint16_t));
    rts[a].counts[sa] = count;
}

uint8_t Rt_ReadSubaddress(uint8_t a, uint8_t sa, uint16_t *out, uint8_t cap)
{
    if (a >= RT_COUNT || sa >= SUBADDRESSES) return 0;
    uint8_t n = rts[a].counts[sa];
    if (n > cap) n = cap;
    memcpy(out, rts[a].data[sa], (size_t)n * sizeof(uint16_t));
    return n;
}

uint32_t Rt_BroadcastCount(uint8_t a)
{
    return (a < RT_COUNT) ? rts[a].broadcasts_received : 0;
}

/* ------------------------------------------------------------------ */
/* bus controller                                                       */
/* ------------------------------------------------------------------ */

static Mil1553Stats_t stats;

void Mil1553_GetStats(Mil1553Stats_t *out) { if (out) *out = stats; }
void Mil1553_ResetStats(void) { memset(&stats, 0, sizeof stats); }

uint16_t Mil1553_EncodeCommand(const Mil1553CommandWord_t *cmd)
{
    /* Word count 32 goes on the wire as 0. There are five bits for a
     * count that runs 1 to 32, so 32 has to borrow the unused zero. */
    uint8_t count_field = (cmd->word_count >= 32) ? 0 : (uint8_t)(cmd->word_count & 0x1F);

    return (uint16_t)(((uint16_t)(cmd->rt_address & 0x1F) << 11) |
                      ((uint16_t)(cmd->tr & 0x01)        << 10) |
                      ((uint16_t)(cmd->subaddress & 0x1F) << 5) |
                       (uint16_t)(count_field & 0x1F));
}

void Mil1553_DecodeCommand(uint16_t raw, Mil1553CommandWord_t *out)
{
    out->rt_address = (uint8_t)((raw >> 11) & 0x1F);
    out->tr         = (uint8_t)((raw >> 10) & 0x01);
    out->subaddress = (uint8_t)((raw >> 5)  & 0x1F);

    uint8_t count_field = (uint8_t)(raw & 0x1F);
    bool is_mode_code = (out->subaddress == MIL1553_MODE_SUBADDRESS_A ||
                         out->subaddress == MIL1553_MODE_SUBADDRESS_B);

    /* On a mode-code subaddress those five bits are the mode code, so
     * they must not be turned into a word count of 32. */
    out->word_count = (!is_mode_code && count_field == 0) ? 32 : count_field;
}

static void fill_status(Mil1553StatusWord_t *s, const Rt_t *rt, uint8_t address, bool broadcast)
{
    memset(s, 0, sizeof *s);
    s->rt_address = address;
    s->busy = rt->busy;
    if (rt->busy)            s->status_flags |= MIL1553_STATUS_BUSY;
    if (rt->subsystem_fault) s->status_flags |= MIL1553_STATUS_SUBSYSTEM_FLAG;
    if (broadcast)           s->status_flags |= MIL1553_STATUS_BROADCAST_RCVD;
}

bool Mil1553_BcTransaction(const Mil1553CommandWord_t *cmd,
                           uint16_t *data_inout, uint8_t data_count,
                           Mil1553StatusWord_t *status_out)
{
    if (!cmd || cmd->rt_address >= RT_COUNT) return false;
    stats.transactions++;

    bool is_mode_code = (cmd->subaddress == MIL1553_MODE_SUBADDRESS_A ||
                         cmd->subaddress == MIL1553_MODE_SUBADDRESS_B);

    if (cmd->rt_address == MIL1553_BROADCAST_ADDRESS) {
        /* Every RT takes the data and NONE of them answers. A BC that
         * waits for a status word here will time out every single time,
         * on a bus that is working perfectly. */
        for (uint8_t a = 0; a < RT_COUNT - 1; a++) {
            if (!rts[a].connected) continue;
            rts[a].broadcasts_received++;
            if (!is_mode_code && cmd->tr == 0 && data_inout)
                Rt_LoadSubaddress(a, cmd->subaddress, data_inout, data_count);
        }
        if (status_out) memset(status_out, 0, sizeof *status_out);
        return true;
    }

    Rt_t *rt = &rts[cmd->rt_address];

    /* Nothing at that address means silence, and silence is a timeout.
     * There is no negative acknowledge on 1553, only an answer or none. */
    if (!rt->connected) {
        stats.failures++;
        return false;
    }

    if (status_out) fill_status(status_out, rt, cmd->rt_address, false);

    /* A busy RT answers with the busy bit and no data. The BC has to
     * treat that as "come back later", not as data it can use. */
    if (rt->busy) {
        stats.failures++;
        return false;
    }

    if (is_mode_code) {
        uint8_t mode = (uint8_t)(cmd->word_count & 0x1F);
        if (mode == MIL1553_MODE_RESET_RT) {
            rt->subsystem_fault = false;
            rt->busy = false;
        }
        /* Transmit Status Word needs no payload: the status the RT sends
         * back is the entire answer. */
        return true;
    }

    uint8_t count = (cmd->word_count == 0) ? 32 : cmd->word_count;
    if (count > MAX_WORDS || data_count < count || !data_inout) {
        stats.failures++;
        if (status_out) status_out->message_error = true;
        return false;
    }

    if (cmd->tr) {
        /* Transmit: RT to BC. */
        uint8_t have = Rt_ReadSubaddress(cmd->rt_address, cmd->subaddress, data_inout, count);
        if (have < count) {
            /* The RT has fewer words than were asked for. On a real bus
             * this shows up as a missing word, which is a message error. */
            stats.failures++;
            if (status_out) status_out->message_error = true;
            return false;
        }
    } else {
        /* Receive: BC to RT. */
        Rt_LoadSubaddress(cmd->rt_address, cmd->subaddress, data_inout, count);
    }

    if (rt->subsystem_fault) {
        /* The transfer worked, but the RT is telling the BC its data is
         * not trustworthy. Delivering the words without the flag is how
         * bad data reaches a flight control law. */
        stats.failures++;
        return false;
    }

    return true;
}

void Mil1553_RunSchedule(const Mil1553CommandWord_t *schedule, uint8_t count, uint32_t minor_frame_ms)
{
    (void)minor_frame_ms;    /* simulated time: the schedule is fixed, so the
                              * order is what matters, not the wall clock */
    uint16_t buffer[MAX_WORDS];
    Mil1553StatusWord_t status;

    for (uint8_t i = 0; i < count; i++) {
        memset(buffer, 0, sizeof buffer);

        if (Mil1553_BcTransaction(&schedule[i], buffer, MAX_WORDS, &status))
            continue;

        /* One retry, then move on. A BC must never stall the whole frame
         * waiting for one sulking terminal: every other RT on the bus has
         * a deadline that does not care. */
        stats.retries++;
        Mil1553_BcTransaction(&schedule[i], buffer, MAX_WORDS, &status);
    }
}
