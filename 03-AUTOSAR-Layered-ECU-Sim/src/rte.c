/* The Runtime Environment: a signal table and a periodic scheduler.
 * Deliberately small. Its value is not what it does but what it stops
 * anyone from doing, which is calling across layers directly. */

#include "rte.h"
#include <string.h>

#define MAX_RUNNABLES 16

typedef struct {
    int32_t  value;
    uint32_t last_write_ms;
    bool     ever_written;
} RteSignal_t;

typedef struct {
    RteRunnable_t fn;
    uint32_t      period_ms;
} RteTask_t;

static RteSignal_t signals[SIG_COUNT];
static RteTask_t   tasks[MAX_RUNNABLES];
static uint8_t     task_count;
static uint32_t    now_ms;

void Rte_Reset(void)
{
    memset(signals, 0, sizeof signals);
    memset(tasks, 0, sizeof tasks);
    task_count = 0;
    now_ms = 0;
}

uint32_t Rte_Now(void) { return now_ms; }

int32_t Rte_Read(RteSignalId_t sig)
{
    if (sig >= SIG_COUNT) return 0;      /* out of range reads 0, never memory */
    return signals[sig].value;
}

void Rte_Write(RteSignalId_t sig, int32_t value)
{
    if (sig >= SIG_COUNT) return;
    signals[sig].value = value;
    signals[sig].last_write_ms = now_ms;
    signals[sig].ever_written = true;
}

bool Rte_IsFresh(RteSignalId_t sig, uint32_t max_age_ms)
{
    if (sig >= SIG_COUNT) return false;
    if (!signals[sig].ever_written) return false;
    return (now_ms - signals[sig].last_write_ms) <= max_age_ms;
}

void Rte_RegisterRunnable(RteRunnable_t fn, uint32_t period_ms)
{
    if (task_count >= MAX_RUNNABLES || !fn || period_ms == 0) return;
    tasks[task_count].fn = fn;
    tasks[task_count].period_ms = period_ms;
    task_count++;
}

void Rte_Start(uint32_t duration_ms, uint32_t tick_ms)
{
    if (tick_ms == 0) return;
    uint32_t end = now_ms + duration_ms;

    /* Time carries on across calls. Restarting the clock at zero would
     * make every signal look freshly written, which is exactly the bug
     * the freshness check exists to catch. */
    while (now_ms < end) {
        now_ms += tick_ms;
        /* Registration order is execution order within a tick, which is
         * why BSW registers first: its data is then already published
         * when the application runnables read it in the same tick. */
        for (uint8_t i = 0; i < task_count; i++)
            if (now_ms % tasks[i].period_ms == 0)
                tasks[i].fn();
    }
}
