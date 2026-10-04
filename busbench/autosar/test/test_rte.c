#include "rte.h"
#include "bsw.h"
#include <stdio.h>
#include <assert.h>

void AppSwc_Init(void);

int main(void)
{
    /* Signal freshness, checked before anything else touches it. */
    Rte_Reset();
    assert(!Rte_IsFresh(SIG_VEHICLE_SPEED, 100));   /* never written yet */
    Rte_Write(SIG_VEHICLE_SPEED, 50);
    assert(Rte_Read(SIG_VEHICLE_SPEED) == 50);
    assert(Rte_IsFresh(SIG_VEHICLE_SPEED, 100));

    /* An out of range signal id must read 0, not memory. */
    assert(Rte_Read(SIG_COUNT) == 0);

    /* Full stack. BSW registers first so its data is published before
     * the application runnables read it in the same tick. */
    Rte_Reset();
    Bsw_Init();
    AppSwc_Init();

    uint8_t chassis[3];

    /* Under the limit, lamp stays off. */
    chassis[0] = 0x27; chassis[1] = 0x10; chassis[2] = 0x00;   /* 100 km/h */
    Bsw_InjectCanFrame(0x101, chassis, 3);
    Rte_Start(60, 10);
    assert(Rte_Read(SIG_VEHICLE_SPEED) == 100);
    assert(!Bsw_LampIsOn());
    printf("100 km/h -> lamp off\n");

    /* Over the limit, lamp latches on. */
    chassis[0] = 0x36; chassis[1] = 0xB0;                       /* 140 km/h */
    Bsw_InjectCanFrame(0x101, chassis, 3);
    Rte_Start(60, 10);
    assert(Bsw_LampIsOn());
    printf("140 km/h -> lamp on\n");

    /* Slowing down alone does not clear it, the driver has to brake. */
    chassis[0] = 0x1F; chassis[1] = 0x40; chassis[2] = 0x00;    /* 80 km/h */
    Bsw_InjectCanFrame(0x101, chassis, 3);
    Rte_Start(60, 10);
    assert(Bsw_LampIsOn());
    printf("80 km/h, no brake -> lamp still on (latched)\n");

    chassis[2] = 0x01;                                          /* brake pressed */
    Bsw_InjectCanFrame(0x101, chassis, 3);
    Rte_Start(60, 10);
    assert(!Bsw_LampIsOn());
    printf("80 km/h + brake -> lamp off\n");

    /* Nothing arrives for half a second. The last good value must not be
     * mistaken for a current one. */
    Rte_Start(500, 10);
    assert(!Rte_IsFresh(SIG_VEHICLE_SPEED, 100));
    assert(Bsw_LampIsOn());
    printf("bus silent -> stale signal -> lamp on\n");

    /* Demo: let the BSW generate its own traffic and watch it flow up. */
    Rte_Reset();
    Bsw_Init();
    AppSwc_Init();
    Bsw_SetTrafficEnabled(true);
    printf("\n  t(ms)   speed   rpm  brake  lamp\n");
    for (int i = 0; i < 6; i++) {
        Rte_Start(200, 10);
        printf("  %5u  %6d  %4d  %5d  %4d\n", Rte_Now(),
               Rte_Read(SIG_VEHICLE_SPEED), Rte_Read(SIG_ENGINE_RPM),
               Rte_Read(SIG_BRAKE_PRESSED), Bsw_LampIsOn());
    }

    printf("\nall assertions passed\n");
    return 0;
}
