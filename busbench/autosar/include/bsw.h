#ifndef BSW_H
#define BSW_H
/* Basic Software: drivers and the CAN stack. The application must never
 * include this file. That rule is the whole architecture, and there is a
 * test that enforces it by scanning the source. */

#include <stdint.h>
#include <stdbool.h>

/* Registers the BSW polling runnable with the RTE. Call before the
 * application registers, so fresh data is already published when the
 * application runnables execute in the same tick. */
void Bsw_Init(void);

/* Test hook: pretend a CAN frame arrived, or a sensor read this value. */
void Bsw_InjectCanFrame(uint32_t can_id, const uint8_t *data, uint8_t len);

/* What the BSW last drove onto the hardware, so a test can observe the
 * output end of the loop. */
bool Bsw_LampIsOn(void);

/* Demo mode: synthesize moving CAN traffic every tick. Off by default,
 * so tests drive the stack with Bsw_InjectCanFrame and get repeatable
 * values. Leaving it off is also how a dead bus is simulated. */
void Bsw_SetTrafficEnabled(bool enabled);

#endif /* BSW_H */
