/* Three independent safety mechanisms that share a file but nothing
 * else: a windowed watchdog, a rate-of-change plausibility check, and a
 * central fault escalator. What they have in common is the rule that a
 * failure must produce a defined state, never undefined behaviour. */

#include "watchdog.h"
#include <math.h>
#include <string.h>

/* ---- windowed watchdog ---- */

static uint32_t win_open, win_close, cycle_start;
static bool     wd_configured;

void Watchdog_Init(uint32_t window_open_ms, uint32_t window_close_ms)
{
    /* An inverted window would accept nothing at all, which looks like a
     * permanently faulty task rather than the configuration bug it is. */
    if (window_open_ms > window_close_ms) { wd_configured = false; return; }
    win_open      = window_open_ms;
    win_close     = window_close_ms;
    cycle_start   = 0;
    wd_configured = true;
}

void Watchdog_Reset(uint32_t now_ms) { cycle_start = now_ms; }

bool Watchdog_Kick(uint32_t now_ms)
{
    if (!wd_configured) return false;

    uint32_t elapsed = now_ms - cycle_start;

    /* Too early is a fault as well. A task spinning in a tight loop kicks
     * far more often than it should, and a plain timeout watchdog would
     * happily call that healthy. */
    if (elapsed < win_open)  return false;
    if (elapsed > win_close) return false;

    cycle_start = now_ms;
    return true;
}

bool Watchdog_Poll(uint32_t now_ms)
{
    if (!wd_configured) return false;
    return (now_ms - cycle_start) <= win_close;
}

/* ---- plausibility ---- */

bool Plausibility_Check(double prev_value, double new_value, double dt_s, double max_rate)
{
    /* No elapsed time means there is nothing to judge, and dividing by it
     * would produce an infinity that then compares as plausible. Refuse. */
    if (!(dt_s > 0.0) || !(max_rate >= 0.0)) return false;
    if (isnan(prev_value) || isnan(new_value)) return false;

    return fabs(new_value - prev_value) / dt_s <= max_rate;
}

/* ---- central fault escalation ---- */

#define MAX_FAULTS 32

typedef struct {
    uint16_t id;
    uint8_t  severity;
    uint8_t  count;
    bool     used;
} FaultEntry_t;

static FaultEntry_t faults[MAX_FAULTS];
static SafeState_t  current_state;

static SafeState_t state_for(uint8_t severity)
{
    if (severity >= 3) return SAFE_STATE_SHUTDOWN;
    if (severity == 2) return SAFE_STATE_LIMP_HOME;
    if (severity == 1) return SAFE_STATE_DEGRADED;
    return SAFE_STATE_NORMAL;
}

/* The worst confirmed fault decides the state. Recomputed from scratch
 * each time, so healing a fault can actually lower the state and two
 * fault sources can never disagree about where the vehicle is. */
static void recompute(void)
{
    SafeState_t worst = SAFE_STATE_NORMAL;
    for (int i = 0; i < MAX_FAULTS; i++) {
        if (!faults[i].used) continue;
        if (faults[i].count < FAULT_DEBOUNCE_COUNT) continue;
        SafeState_t s = state_for(faults[i].severity);
        if (s > worst) worst = s;
    }
    current_state = worst;
}

static FaultEntry_t *slot_for(uint16_t fault_id)
{
    FaultEntry_t *free_slot = NULL;
    for (int i = 0; i < MAX_FAULTS; i++) {
        if (faults[i].used && faults[i].id == fault_id) return &faults[i];
        if (!faults[i].used && !free_slot) free_slot = &faults[i];
    }
    return free_slot;
}

SafeState_t Fault_Report(uint16_t fault_id, uint8_t severity)
{
    FaultEntry_t *f = slot_for(fault_id);

    /* Running out of slots is itself a fault, and the safe answer is the
     * most restrictive state rather than a quiet "everything is fine". */
    if (!f) return SAFE_STATE_SHUTDOWN;

    if (!f->used) { f->used = true; f->id = fault_id; f->count = 0; }
    f->severity = severity;
    if (f->count < FAULT_DEBOUNCE_COUNT) f->count++;

    recompute();
    return current_state;
}

void Fault_Heal(uint16_t fault_id)
{
    for (int i = 0; i < MAX_FAULTS; i++) {
        if (faults[i].used && faults[i].id == fault_id) {
            faults[i].used = false;
            faults[i].count = 0;
            break;
        }
    }
    recompute();
}

SafeState_t Fault_GetState(void) { return current_state; }

void Fault_ResetAll(void)
{
    memset(faults, 0, sizeof faults);
    current_state = SAFE_STATE_NORMAL;
}
