#ifndef UDS_CLIENT_H
#define UDS_CLIENT_H
/* Project 2: UDS Diagnostic CLIENT (the scan-tool side, not the ECU side).
 * Talks ISO 14229 over ISO-TP (ISO 15765-2) segmented CAN frames.
 * Goal: learn the request/response state machine a real diagnostic
 * tool (ODIS, CANoe, a cheap OBD dongle) implements. */

#include <stdint.h>
#include <stdbool.h>
#include "isotp.h"

typedef enum { UDS_OK, UDS_TIMEOUT, UDS_NEGATIVE_RESPONSE, UDS_TX_ERROR } UdsResult_t;

/* added: where the frames go. Point this at the simulated ECU, or at a
 * real CAN driver later without touching anything else in this file. */
void Uds_SetTransport(IsoTpSendFrame_t send, IsoTpRecvFrame_t recv);

/* Sends a DiagnosticSessionControl (0x10) request, e.g. to enter the
 * "extended" session needed before privileged services work. */
UdsResult_t Uds_StartSession(uint8_t session_type);

/* ReadDataByIdentifier (0x22) - the most common service: read a live
 * value or a stored config (VIN, software version, sensor reading). */
UdsResult_t Uds_ReadDataByIdentifier(uint16_t did, uint8_t *out, uint16_t out_cap, uint16_t *out_len);

/* added: step one of the handshake. SecurityAccess is two exchanges and
 * the seed has to come back to the caller before a key can be built. */
UdsResult_t Uds_RequestSeed(uint8_t level, uint8_t *seed_out, uint16_t cap, uint16_t *len_out);

/* SecurityAccess (0x27) - two-step seed/key handshake required before
 * WriteDataByIdentifier or RoutineControl will be accepted. */
UdsResult_t Uds_SecurityAccess(uint8_t level, const uint8_t *key, uint16_t key_len);

/* added: the service security exists to protect, so the lock can be
 * shown actually locking something. */
UdsResult_t Uds_WriteDataByIdentifier(uint16_t did, const uint8_t *data, uint16_t len);

/* added: which negative response code came back, valid after
 * UDS_NEGATIVE_RESPONSE. */
uint8_t Uds_GetLastNrc(void);

#endif /* UDS_CLIENT_H */
