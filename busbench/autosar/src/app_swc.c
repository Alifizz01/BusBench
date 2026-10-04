/* Application software component: the overspeed warning.
 *
 * Note what this file includes. Only rte.h. It cannot see a CAN ID, a
 * register, or a driver function, so it does not care whether the speed
 * came from CAN, an analogue sensor, or a test harness. That is the
 * entire benefit of the layering, and it is why the same file could be
 * moved to a different ECU without editing a line. */

#include "rte.h"

#define SPEED_LIMIT_KMH 120
#define SIGNAL_TIMEOUT_MS 100

static bool overspeed_latched;

static void OverspeedMonitor_Run(void)
{
    /* A stale signal is not a slow signal, it is a missing one. Treating
     * the last known value as current is how a warning lamp ends up
     * reflecting a bus that died a minute ago. */
    if (!Rte_IsFresh(SIG_VEHICLE_SPEED, SIGNAL_TIMEOUT_MS)) {
        Rte_Write(SIG_WARNING_LAMP, 1);        /* fail visible, not silent */
        return;
    }

    int32_t speed = Rte_Read(SIG_VEHICLE_SPEED);

    if (speed > SPEED_LIMIT_KMH) overspeed_latched = true;
    /* Braking is what clears it, so the driver has to react. */
    if (Rte_Read(SIG_BRAKE_PRESSED) && speed <= SPEED_LIMIT_KMH) overspeed_latched = false;

    Rte_Write(SIG_WARNING_LAMP, overspeed_latched ? 1 : 0);
}

void AppSwc_Init(void)
{
    overspeed_latched = false;
    Rte_RegisterRunnable(OverspeedMonitor_Run, 20);
}
