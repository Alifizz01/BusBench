#ifndef PARTITION_SCHED_H
#define PARTITION_SCHED_H
/* Project 8: ARINC 653 Time/Space Partitioning Scheduler.
 * Goal: simulate how flight software of DIFFERENT criticality shares
 * one CPU safely - each partition gets a fixed time slice in a
 * repeating major frame, and can NEVER see another partition's memory
 * or steal its CPU time, no matter how buggy it is. Build this as a
 * cooperative scheduler on a normal PC to learn the concept without
 * needing a real RTOS. */

#include <stdint.h>
#include <stdbool.h>

#define PART_MAX_PARTITIONS 8
#define PART_MAX_REGIONS    8
#define PART_REGION_WORDS   16

typedef struct {
    char     name[16];
    uint32_t offset_ms;     /* start time within the major frame */
    uint32_t duration_ms;    /* fixed time slice length - never exceeded */
    void   (*entry_point)(void);
    uint8_t  memory_region_id; /* which isolated memory pool this partition may touch */
} Partition_t;

/* Registers the fixed schedule (partitions + their slices) that
 * together must not exceed major_frame_ms - this is configured
 * OFFLINE at build time in real ARINC 653 systems, not at runtime,
 * which is exactly why it's certifiable: nothing can change it later. */
void PartitionSched_Configure(const Partition_t *partitions, uint8_t count, uint32_t major_frame_ms);

/* added: a schedule with overlapping slices, or one that does not fit in
 * the major frame, is a build error and not something to discover in the
 * air. Configure rejects it and this reports that it did. */
bool PartitionSched_ConfigIsValid(void);

/* Runs the scheduler loop: at each partition's offset, switch memory
 * context (simulated), run entry_point for AT MOST duration_ms, then
 * forcibly preempt even if the partition isn't done - a hung partition
 * can only ever hurt itself.
 *
 * added detail: one call runs exactly ONE major frame, so a test can
 * observe the result instead of never returning. */
void PartitionSched_Run(void);
void PartitionSched_RunFrames(uint32_t frames);

/* added: how a partition consumes its slice. Returns false once the
 * budget is gone, which is this simulator's version of being preempted.
 * A partition that ignores the answer and keeps working still cannot
 * take time from anyone else: the frame advances on the clock, not on
 * the partition finishing. */
bool Part_Work(uint32_t ms);

/* added: space partitioning. Every access names a region, and a
 * partition may only touch its own. This is what an MPU does in
 * hardware; here it is checked at the API boundary. */
bool Part_Write(uint8_t region_id, uint16_t index, int32_t value);
bool Part_Read(uint8_t region_id, uint16_t index, int32_t *out);

/* added: the health monitor. In ARINC 653 a partition fault is recorded
 * and handled by policy, never allowed to propagate. */
uint32_t Hm_OverrunCount(const char *partition_name);
uint32_t Hm_ViolationCount(const char *partition_name);
uint32_t Hm_FrameCount(void);
void     Hm_Reset(void);

/* added: which partition is running, for tests and for the demo log. */
const char *PartitionSched_CurrentName(void);
uint32_t    PartitionSched_Now(void);

#endif /* PARTITION_SCHED_H */
