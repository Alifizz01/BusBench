#ifndef DOIP_GATEWAY_H
#define DOIP_GATEWAY_H
/* Project 5: DoIP Gateway (Diagnostics over IP, ISO 13400).
 * Goal: bridge CAN-based UDS diagnostics onto Ethernet/TCP - the
 * pattern every modern car uses so a garage can plug an Ethernet
 * cable (or use WiFi) instead of a CAN-only OBD dongle. Learn socket
 * programming AND automotive protocol translation in one project. */

#include <stdint.h>
#include <stdbool.h>

/* Every DoIP message starts with the same 8 bytes:
 *   version | inverse version | payload type (2) | payload length (4)
 * The inverse version is a cheap sanity check: if byte 1 is not the
 * bitwise complement of byte 0, this is not a DoIP stream at all. */
#define DOIP_VERSION      0x02      /* ISO 13400-2:2012 */
#define DOIP_HEADER_LEN   8
#define DOIP_TCP_PORT     13400

/* DoIP payload types (ISO 13400 table), the ones worth implementing: */
typedef enum {
    DOIP_GENERIC_NACK            = 0x0000,
    DOIP_VEHICLE_IDENT_REQ   = 0x0001,
    DOIP_VEHICLE_IDENT_RESP  = 0x0004,
    DOIP_ROUTING_ACTIVATION_REQ  = 0x0005,
    DOIP_ROUTING_ACTIVATION_RESP = 0x0006,
    DOIP_DIAG_MESSAGE            = 0x8001, /* carries a raw UDS payload */
    DOIP_DIAG_ACK                = 0x8002,
    DOIP_DIAG_NACK               = 0x8003
} DoipPayloadType_t;

/* Generic negative acknowledge codes. */
#define DOIP_NACK_INCORRECT_PATTERN   0x00
#define DOIP_NACK_UNKNOWN_PAYLOAD     0x01
#define DOIP_NACK_MESSAGE_TOO_LARGE   0x02
#define DOIP_NACK_INVALID_LENGTH      0x04

/* Routing activation response codes. */
#define DOIP_ROUTING_UNKNOWN_SOURCE   0x00
#define DOIP_ROUTING_SUCCESS          0x10

/* Diagnostic message negative ack codes. */
#define DOIP_DIAG_NACK_UNKNOWN_TARGET 0x03

#define DOIP_TESTER_ADDRESS  0x0E00
#define DOIP_ENTITY_ADDRESS  0x0010

/* Starts the TCP server (port 13400) that accepts a tester connection,
 * performs routing activation, then forwards DOIP_DIAG_MESSAGE payloads
 * onto the internal CAN bus as UDS requests (and responses back). */
bool DoipGateway_Start(uint16_t tcp_port);

/* Called whenever a UDS response arrives on CAN, wraps it in a DoIP
 * diagnostic-message frame and sends it back over the open TCP socket. */
void DoipGateway_OnCanUdsResponse(const uint8_t *uds_resp, uint16_t len);

/* added: the gateway does not implement UDS, it forwards it. This is the
 * seam where the real CAN side goes; the demo plugs a small ECU in. */
typedef void (*DoipUdsHandler_t)(const uint8_t *req, uint16_t req_len,
                                 uint8_t *resp, uint16_t resp_cap, uint16_t *resp_len);
void DoipGateway_SetUdsHandler(DoipUdsHandler_t fn);

/* added: framing helpers, so the protocol can be tested without a socket.
 * Both return the number of bytes written, or -1. */
int  Doip_Build(uint16_t payload_type, const uint8_t *payload, uint32_t payload_len,
                uint8_t *out, uint32_t out_cap);
int  Doip_ParseHeader(const uint8_t *in, uint32_t in_len,
                      uint16_t *type_out, uint32_t *payload_len_out);

/* added: the whole request/response step with no networking involved.
 * Returns bytes written to out, or -1 if nothing should be sent. */
int  DoipGateway_HandleMessage(const uint8_t *in, uint32_t in_len,
                               uint8_t *out, uint32_t out_cap);

/* added: routing activation is a state, and diagnostics before it must
 * be refused. */
bool DoipGateway_IsRoutingActive(void);
void DoipGateway_ResetSession(void);

#endif /* DOIP_GATEWAY_H */
