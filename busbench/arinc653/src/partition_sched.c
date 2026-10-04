/* ARINC 653 time and space partitioning.
 *
 * The idea worth taking away: the major frame advances on the clock, not
 * on partitions finishing. A partition that runs long is cut off at its
 * boundary and the next one still starts exactly on its offset. That is
 * what makes it safe to run a badly behaved partition next to a critical
 * one, and it is why the schedule is fixed offline rather than computed
 * at runtime by something that could get it wrong. */

#include "partition_sched.h"
#include <string.h>

typedef struct {
    uint32_t overruns;
    uint32_t violations;
} Health_t;

static Partition_t partitions[PART_MAX_PARTITIONS];
static Health_t    health[PART_MAX_PARTITIONS];
static uint8_t     partition_count;
static uint32_t    major_frame;
static bool        config_valid;
static uint32_t    frames_run;

static int32_t     regions[PART_MAX_REGIONS][PART_REGION_WORDS];

/* Set only while a partition is executing. */
static int      current = -1;
static uint32_t budget_left;
static uint32_t now_ms;

void Hm_Reset(void)
{
    memset(health, 0, sizeof health);
    memset(regions, 0, sizeof regions);
    frames_run = 0;
    now_ms = 0;
}

uint32_t Hm_FrameCount(void) { return frames_run; }

static int find_partition(const char *name)
{
    for (uint8_t i = 0; i < partition_count; i++)
        if (strcmp(partitions[i].name, name) == 0) return i;
    return -1;
}

uint32_t Hm_OverrunCount(const char *name)
{
    int i = find_partition(name);
    return (i < 0) ? 0 : health[i].overruns;
}

uint32_t Hm_ViolationCount(const char *name)
{
    int i = find_partition(name);
    return (i < 0) ? 0 : health[i].violations;
}

const char *PartitionSched_CurrentName(void)
{
    return (current < 0) ? "" : partitions[current].name;
}

uint32_t PartitionSched_Now(void) { return now_ms; }

void PartitionSched_Configure(const Partition_t *parts, uint8_t count, uint32_t major_frame_ms)
{
    config_valid = false;
    partition_count = 0;
    major_frame = major_frame_ms;
    memset(partitions, 0, sizeof partitions);
    Hm_Reset();

    if (!parts || count == 0 || count > PART_MAX_PARTITIONS || major_frame_ms == 0) return;

    for (uint8_t i = 0; i < count; i++) {
        if (parts[i].duration_ms == 0) return;
        if (parts[i].memory_region_id >= PART_MAX_REGIONS) return;
        /* A slice that runs past the end of the frame would silently eat
         * into the next frame's first partition. */
        if (parts[i].offset_ms + parts[i].duration_ms > major_frame_ms) return;

        for (uint8_t j = 0; j < i; j++) {
            uint32_t a0 = parts[i].offset_ms, a1 = a0 + parts[i].duration_ms;
            uint32_t b0 = parts[j].offset_ms, b1 = b0 + parts[j].duration_ms;
            /* Overlapping slices mean two partitions think they own the
             * same microsecond, which is the one thing this design exists
             * to make impossible. Reject the schedule at build time. */
            if (a0 < b1 && b0 < a1) return;
        }
    }

    memcpy(partitions, parts, (size_t)count * sizeof(Partition_t));
    partition_count = count;
    config_valid = true;
}

bool PartitionSched_ConfigIsValid(void) { return config_valid; }

bool Part_Work(uint32_t ms)
{
    if (current < 0) return false;

    if (ms > budget_left) {
        /* The slice is over. The partition is told to stop, and the fact
         * that it wanted more is recorded against it and nobody else. */
        now_ms += budget_left;
        budget_left = 0;
        health[current].overruns++;
        return false;
    }

    budget_left -= ms;
    now_ms += ms;
    return true;
}

bool Part_Write(uint8_t region_id, uint16_t index, int32_t value)
{
    if (current < 0) return false;
    if (index >= PART_REGION_WORDS) return false;

    /* Space partitioning. An MPU would trap this in hardware; here it is
     * refused at the API boundary and logged against the partition that
     * tried it. Either way the neighbour's memory is untouched. */
    if (region_id != partitions[current].memory_region_id) {
        health[current].violations++;
        return false;
    }

    regions[region_id][index] = value;
    return true;
}

bool Part_Read(uint8_t region_id, uint16_t index, int32_t *out)
{
    if (current < 0 || !out) return false;
    if (index >= PART_REGION_WORDS) return false;

    if (region_id != partitions[current].memory_region_id) {
        health[current].violations++;
        return false;
    }

    *out = regions[region_id][index];
    return true;
}

void PartitionSched_Run(void) { PartitionSched_RunFrames(1); }

void PartitionSched_RunFrames(uint32_t frames)
{
    if (!config_valid) return;

    for (uint32_t f = 0; f < frames; f++) {
        uint32_t frame_start = now_ms;

        for (uint8_t i = 0; i < partition_count; i++) {
            /* Each partition starts at its offset, whatever the previous
             * one did with its own slice. This single line is the whole
             * guarantee. */
            now_ms = frame_start + partitions[i].offset_ms;

            current = i;
            budget_left = partitions[i].duration_ms;
            if (partitions[i].entry_point) partitions[i].entry_point();
            current = -1;
        }

        now_ms = frame_start + major_frame;
        frames_run++;
    }
}
