#ifndef CAN_SNIFFER_H
#define CAN_SNIFFER_H
/* Project 1: CAN Bus Sniffer & DBC Decoder
 * Goal: capture raw CAN frames off a bus (or a log file) and turn them
 * into human-readable signals using a DBC file (the industry-standard
 * "dictionary" that maps a CAN ID + bit range -> signal name/scale/unit).
 * This is the FIRST tool every automotive software engineer touches -
 * before you write an ECU, you need to be able to read what's on the bus. */

#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint32_t id;
    uint8_t  dlc;
    uint8_t  data[8];
    uint64_t timestamp_us;
} CanRawFrame_t;

typedef struct {
    char     name[32];
    uint32_t can_id;
    uint8_t  start_bit;
    uint8_t  length_bits;
    bool     little_endian;
    bool     is_signed;      /* added: DBC "@1-" / "@0-" means two's complement */
    double   scale, offset;
    char     unit[8];
} DbcSignal_t;

/* Loads a (simplified) DBC file into an array of signal definitions. */
int   Dbc_Load(const char *path, DbcSignal_t *out, int max_signals);

/* Extracts one signal's physical value from a raw frame, given its
 * DBC definition. Returns false if frame.id != signal.can_id. */
bool  Dbc_Decode(const DbcSignal_t *sig, const CanRawFrame_t *frame, double *value_out);

/* added: reads a candump-style log file, the format `candump -l` writes:
 *   (1730000000.123456) can0 100#1F4000000000000
 * so the decoder can be exercised without a real interface. */
int   Can_ReadLog(const char *path, CanRawFrame_t *out, int max_frames);

#endif /* CAN_SNIFFER_H */
