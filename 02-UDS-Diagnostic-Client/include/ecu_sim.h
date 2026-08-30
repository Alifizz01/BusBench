#ifndef ECU_SIM_H
#define ECU_SIM_H
/* A stand-in ECU so the client has something to talk to. It answers a
 * handful of real UDS services and, importantly, refuses things the way
 * a real ECU refuses them: wrong session, locked, unknown identifier. */

#include <stdint.h>
#include <stdbool.h>

void EcuSim_Reset(void);

/* The two ends of the simulated CAN link. */
void EcuSim_ClientSend(const uint8_t *frame, uint8_t len);   /* tester -> ECU */
bool EcuSim_ClientRecv(uint8_t *frame, uint8_t *len);        /* ECU -> tester */

bool EcuSim_IsUnlocked(void);

#endif /* ECU_SIM_H */
