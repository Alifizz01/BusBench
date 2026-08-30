#ifndef RTE_H
#define RTE_H
/* Project 3: AUTOSAR-style Layered ECU Simulator.
 * Goal: build the classic 3-layer stack (BSW / RTE / Application) as a
 * PC-runnable simulation - no real ECU needed. The RTE (Runtime
 * Environment) is the point of this project: it is the ONLY module
 * that both BSW and Application are allowed to import. Application
 * code must never #include a driver header directly - that coupling
 * is the exact mistake AUTOSAR exists to prevent. */

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    SIG_VEHICLE_SPEED,
    SIG_ENGINE_RPM,
    SIG_BRAKE_PRESSED,
    SIG_WARNING_LAMP,     /* added: an output, so the app has something to drive */
    SIG_COUNT
} RteSignalId_t;

/* Application layer calls this to read a signal - it has NO idea
 * whether the value came from CAN, a sensor ADC, or a simulator. */
int32_t Rte_Read(RteSignalId_t sig);

/* BSW layer calls this when new raw data arrives, to publish it. */
void    Rte_Write(RteSignalId_t sig, int32_t value);

/* Application registers a periodic runnable (the AUTOSAR "task"
 * concept) instead of writing its own while(1) loop. */
typedef void (*RteRunnable_t)(void);
void    Rte_RegisterRunnable(RteRunnable_t fn, uint32_t period_ms);

/* added: a signal that stopped updating is a fault, not a valid old
 * value. Real AUTOSAR calls this signal timeout and substitutes a
 * default; here the caller asks and decides. */
bool    Rte_IsFresh(RteSignalId_t sig, uint32_t max_age_ms);

/* added: the scheduler. Runs every registered runnable at its own
 * period until duration_ms of simulated time has elapsed. */
void    Rte_Start(uint32_t duration_ms, uint32_t tick_ms);
void    Rte_Reset(void);
uint32_t Rte_Now(void);

#endif /* RTE_H */
