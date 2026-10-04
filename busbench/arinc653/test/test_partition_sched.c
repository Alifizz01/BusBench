#include "partition_sched.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

/* Three partitions of different quality, sharing one CPU. */

static uint32_t fms_runs, greedy_runs, nosy_runs;
static uint32_t fms_start_time, nosy_start_time;
static int32_t  fms_readback;

/* Well behaved: does its work and stops. */
static void flight_management(void)
{
    fms_start_time = PartitionSched_Now();
    fms_runs++;
    /* Read back what this partition itself left here last frame. If the
     * isolation leaks, the neighbour's 999 shows up instead. */
    Part_Read(0, 0, &fms_readback);
    Part_Work(3);
    Part_Write(0, 0, (int32_t)fms_runs);
}

/* Buggy: an infinite loop. It must only ever hurt itself. */
static void greedy_partition(void)
{
    greedy_runs++;
    while (Part_Work(1)) { }        /* keeps asking until it is cut off */
}

/* Malicious or just wrong: reaches into someone else's memory. */
static void nosy_partition(void)
{
    nosy_start_time = PartitionSched_Now();
    nosy_runs++;
    int32_t stolen = 0;
    Part_Read(0, 0, &stolen);       /* region 0 belongs to flight management */
    Part_Write(0, 0, 999);
    Part_Write(2, 0, 42);           /* its own region, allowed */
}

int main(void)
{
    Partition_t schedule[] = {
        { "FMS",    0, 10, flight_management, 0 },
        { "GREEDY", 10, 5, greedy_partition,  1 },
        { "NOSY",   15, 5, nosy_partition,    2 },
    };

    /* An overlapping schedule is a build error, not a surprise in the air. */
    Partition_t overlapping[] = {
        { "A", 0, 10, flight_management, 0 },
        { "B", 5, 10, flight_management, 1 },
    };
    PartitionSched_Configure(overlapping, 2, 40);
    assert(!PartitionSched_ConfigIsValid());

    /* So is a slice that runs off the end of the major frame. */
    Partition_t too_long[] = { { "A", 30, 20, flight_management, 0 } };
    PartitionSched_Configure(too_long, 1, 40);
    assert(!PartitionSched_ConfigIsValid());
    printf("bad schedules rejected at configuration time\n");

    PartitionSched_Configure(schedule, 3, 40);
    assert(PartitionSched_ConfigIsValid());

    PartitionSched_RunFrames(3);

    /* Every partition ran every frame, including the two after the one
     * that never finished. */
    assert(fms_runs == 3 && greedy_runs == 3 && nosy_runs == 3);
    printf("all 3 partitions ran in all 3 frames\n");

    /* The greedy partition was cut off every time, and only its own
     * counter moved. */
    assert(Hm_OverrunCount("GREEDY") == 3);
    assert(Hm_OverrunCount("FMS") == 0);
    assert(Hm_OverrunCount("NOSY") == 0);
    printf("GREEDY overran %u times and stole nothing\n", Hm_OverrunCount("GREEDY"));

    /* The proof: NOSY still started exactly on its offset in the last
     * frame, even though the partition before it ran off the end. */
    assert(nosy_start_time == 2 * 40 + 15);
    assert(fms_start_time == 2 * 40 + 0);
    printf("NOSY still started at t=%u, exactly its offset\n", nosy_start_time);

    /* The cross-partition read and write were both refused. */
    assert(Hm_ViolationCount("NOSY") == 6);      /* one read + one write, 3 frames */
    printf("NOSY was refused %u cross-partition accesses\n", Hm_ViolationCount("NOSY"));

    /* And FMS memory still holds what FMS wrote, not the 999 that NOSY
     * tried to put there. */
    assert(fms_readback == 2);
    printf("FMS read back its own %d, never the 999 from next door\n", fms_readback);

    assert(Hm_FrameCount() == 3);

    printf("\nall assertions passed\n");
    return 0;
}
