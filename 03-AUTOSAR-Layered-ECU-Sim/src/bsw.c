/* Basic Software: the simulated CAN driver and the lamp output driver.
 * It talks to hardware on one side and to the RTE on the other, and it
 * never calls the application. Data flows up through Rte_Write, commands
 * flow down through Rte_Read. */

#include "bsw.h"
#include "rte.h"
#include <string.h>

#define CAN_ID_ENGINE  0x100
#define CAN_ID_CHASSIS 0x101

static uint8_t last_engine[8];
static uint8_t last_chassis[8];
static bool    lamp_on;
static bool    traffic_enabled;
static uint32_t sim_tick;

static void publish_engine(void)
{
    /* Same bit layout as project 1: raw counts, scaled here so the
     * application only ever sees engineering units. */
    int32_t rpm = (int32_t)(((uint32_t)last_engine[1] << 8) | last_engine[0]) / 4;
    Rte_Write(SIG_ENGINE_RPM, rpm);
}

static void publish_chassis(void)
{
    int32_t speed = (int32_t)(((uint32_t)last_chassis[0] << 8) | last_chassis[1]) / 100;
    Rte_Write(SIG_VEHICLE_SPEED, speed);
    Rte_Write(SIG_BRAKE_PRESSED, (last_chassis[2] & 0x01) ? 1 : 0);
}

/* The BSW main function, scheduled by the RTE like any other runnable.
 * In real AUTOSAR the BSW Scheduler does this, but the shape is the same. */
static void Bsw_MainFunction(void)
{
    if (traffic_enabled) {
        /* Stand in for real traffic: a ramp so the values move. */
        sim_tick++;
        uint32_t rpm_raw = 3200 + (sim_tick % 40) * 100;      /* 800 to 1800 rpm */
        last_engine[0] = (uint8_t)(rpm_raw & 0xFF);
        last_engine[1] = (uint8_t)(rpm_raw >> 8);

        uint32_t speed_raw = (sim_tick % 200) * 100;          /* 0 to 199 km/h */
        last_chassis[0] = (uint8_t)(speed_raw >> 8);
        last_chassis[1] = (uint8_t)(speed_raw & 0xFF);
        last_chassis[2] = (sim_tick % 50) < 5 ? 0x01 : 0x00;  /* brake taps */

        publish_engine();
        publish_chassis();
    }

    /* Output direction: whatever the application decided last tick. */
    lamp_on = Rte_Read(SIG_WARNING_LAMP) != 0;
}

void Bsw_Init(void)
{
    memset(last_engine, 0, sizeof last_engine);
    memset(last_chassis, 0, sizeof last_chassis);
    lamp_on = false;
    traffic_enabled = false;
    sim_tick = 0;
    Rte_RegisterRunnable(Bsw_MainFunction, 10);
}

void Bsw_InjectCanFrame(uint32_t can_id, const uint8_t *data, uint8_t len)
{
    if (len > 8) len = 8;
    if (can_id == CAN_ID_ENGINE) {
        memcpy(last_engine, data, len);
        publish_engine();
    } else if (can_id == CAN_ID_CHASSIS) {
        memcpy(last_chassis, data, len);
        publish_chassis();
    }
}

bool Bsw_LampIsOn(void) { return lamp_on; }

void Bsw_SetTrafficEnabled(bool enabled) { traffic_enabled = enabled; }
