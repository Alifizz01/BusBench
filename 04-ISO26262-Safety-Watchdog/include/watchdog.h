#ifndef WATCHDOG_H
#define WATCHDOG_H
/* Project 4: ISO 26262 Safety Watchdog / Fault Monitor.
 * Goal: implement the pattern that keeps a car from doing something
 * dangerous when software misbehaves - windowed watchdog kicks,
 * range/plausibility checks, and a "go to safe state" transition.
 * This is the smallest project but the most safety-standard-heavy. */

#include <stdint.h>
#include <stdbool.h>

typedef enum { SAFE_STATE_NORMAL, SAFE_STATE_DEGRADED, SAFE_STATE_LIMP_HOME, SAFE_STATE_SHUTDOWN } SafeState_t;

/* Windowed watchdog: the monitored task must call Watchdog_Kick()
 * inside [window_open_ms, window_close_ms] every cycle - too early
 * OR too late both count as a fault (catches a task stuck in a tight
 * loop just as well as a task that hung). */
void Watchdog_Init(uint32_t window_open_ms, uint32_t window_close_ms);
bool Watchdog_Kick(uint32_t now_ms);          /* false = outside window, fault raised */

/* added: a real windowed watchdog is hardware and expires on its own, so
 * a task that stops kicking entirely must still be caught. Call this
 * every cycle; false means the window closed with no kick. */
bool Watchdog_Poll(uint32_t now_ms);

/* added: restarts the window at now_ms, after a handled fault. */
void Watchdog_Reset(uint32_t now_ms);

/* Plausibility check: is this sensor value physically possible given
 * the previous value and elapsed time (rate-of-change limit)? */
bool Plausibility_Check(double prev_value, double new_value, double dt_s, double max_rate);

/* Central fault escalation - every fault source reports here, this
 * function decides the resulting SafeState_t (single source of truth,
 * so two faults can never independently pick two different safe states). */
SafeState_t Fault_Report(uint16_t fault_id, uint8_t severity);

/* added: a fault has to persist before it counts. One glitchy reading
 * must not put the car into limp home. */
#define FAULT_DEBOUNCE_COUNT 3

/* added: read the state without reporting anything new, clear a fault
 * that has genuinely gone away, and reset the monitor between runs. */
SafeState_t Fault_GetState(void);
void        Fault_Heal(uint16_t fault_id);
void        Fault_ResetAll(void);

#endif /* WATCHDOG_H */
