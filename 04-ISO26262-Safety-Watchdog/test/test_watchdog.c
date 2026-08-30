#include "watchdog.h"
#include <stdio.h>
#include <assert.h>

int main(void)
{
    /* Window is 8 to 12 ms, so a 10 ms task is healthy. */
    Watchdog_Init(8, 12);

    assert(Watchdog_Kick(10));          /* on time */
    assert(Watchdog_Kick(20));
    assert(!Watchdog_Kick(22));         /* 2 ms later, far too early */
    Watchdog_Reset(22);
    assert(!Watchdog_Kick(40));         /* 18 ms later, too late */
    printf("windowed watchdog rejects both early and late kicks\n");

    /* A task that stops kicking entirely must still be caught. */
    Watchdog_Reset(100);
    assert(Watchdog_Poll(110));
    assert(!Watchdog_Poll(120));
    printf("silent task caught by the poll\n");

    /* An inverted window is a configuration bug, not a healthy state. */
    Watchdog_Init(20, 10);
    assert(!Watchdog_Kick(15));

    /* Plausibility: 0 to 100 km/h in 100 ms is not a real car. */
    assert(Plausibility_Check(0.0, 5.0, 0.1, 100.0));       /* 50 km/h per s */
    assert(!Plausibility_Check(0.0, 100.0, 0.1, 100.0));    /* 1000 km/h per s */
    assert(Plausibility_Check(80.0, 75.0, 0.1, 100.0));     /* braking, still fine */
    /* Zero elapsed time cannot be judged, and must not divide by zero. */
    assert(!Plausibility_Check(0.0, 1.0, 0.0, 100.0));
    printf("plausibility rejects impossible rates of change\n");

    /* Fault escalation. One report is not a fault, it is a glitch. */
    Fault_ResetAll();
    assert(Fault_Report(0x100, 2) == SAFE_STATE_NORMAL);
    assert(Fault_Report(0x100, 2) == SAFE_STATE_NORMAL);
    assert(Fault_Report(0x100, 2) == SAFE_STATE_LIMP_HOME);   /* third, confirmed */
    printf("fault confirmed only after %d reports\n", FAULT_DEBOUNCE_COUNT);

    /* A milder fault must not talk the state back down. */
    for (int i = 0; i < FAULT_DEBOUNCE_COUNT; i++) Fault_Report(0x200, 1);
    assert(Fault_GetState() == SAFE_STATE_LIMP_HOME);

    /* A worse one must escalate immediately once confirmed. */
    for (int i = 0; i < FAULT_DEBOUNCE_COUNT; i++) Fault_Report(0x300, 3);
    assert(Fault_GetState() == SAFE_STATE_SHUTDOWN);
    printf("worst confirmed fault wins, mild faults cannot override it\n");

    /* Healing the worst fault drops back to the next worst, not to normal. */
    Fault_Heal(0x300);
    assert(Fault_GetState() == SAFE_STATE_LIMP_HOME);
    Fault_Heal(0x100);
    assert(Fault_GetState() == SAFE_STATE_DEGRADED);
    Fault_Heal(0x200);
    assert(Fault_GetState() == SAFE_STATE_NORMAL);
    printf("healing steps back down one level at a time\n");

    /* Out of fault slots is itself unsafe, so it must not read as fine. */
    Fault_ResetAll();
    for (int i = 0; i < 40; i++) {
        SafeState_t s = Fault_Report((uint16_t)(0x1000 + i), 1);
        if (i >= 32) assert(s == SAFE_STATE_SHUTDOWN);
    }
    printf("fault table overflow reports shutdown, not normal\n");

    printf("\nall assertions passed\n");
    return 0;
}
