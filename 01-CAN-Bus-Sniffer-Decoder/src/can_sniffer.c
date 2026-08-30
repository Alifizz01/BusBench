/* CAN sniffer / DBC decoder implementation.
 * The only genuinely tricky part is bit extraction: a DBC signal can be
 * laid out Intel (little endian) or Motorola (big endian), and the two
 * walk the message bits in opposite directions. Everything else is
 * parsing and scaling. */

#include "can_sniffer.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* CAN bit numbering used by DBC files: bit index i lives in byte i/8 at
 * bit position i%8, where bit 0 of a byte is its least significant bit. */
static int get_bit(const uint8_t *data, int i)
{
    return (data[i >> 3] >> (i & 7)) & 1;
}

int Dbc_Load(const char *path, DbcSignal_t *out, int max_signals)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    char line[512];
    uint32_t current_id = 0;
    int n = 0;

    while (fgets(line, sizeof line, f)) {
        unsigned int id;
        char msgname[64];

        /* A message header resets which CAN ID the following signals
         * belong to: "BO_ 100 EngineData: 8 ECU". */
        if (sscanf(line, " BO_ %u %63[^:]:", &id, msgname) == 2) {
            current_id = id;
            continue;
        }

        /* "SG_ EngineSpeed : 0|16@1+ (0.25,0) [0|16383.75] "rpm" ECU" */
        unsigned int sb, len, order;
        char sign = '+';
        double scale = 1.0, offset = 0.0, mn = 0.0, mx = 0.0;
        char name[32], unit[8];
        name[0] = unit[0] = '\0';

        int got = sscanf(line, " SG_ %31s : %u|%u@%u%c (%lf,%lf) [%lf|%lf] \"%7[^\"]\"",
                         name, &sb, &len, &order, &sign, &scale, &offset, &mn, &mx, unit);
        if (got < 7) continue;
        if (n >= max_signals) break;
        if (len == 0 || len > 64 || sb > 63) continue;   /* malformed, skip */

        DbcSignal_t *s = &out[n++];
        memset(s, 0, sizeof *s);
        snprintf(s->name, sizeof s->name, "%s", name);
        s->can_id        = current_id;
        s->start_bit     = (uint8_t)sb;
        s->length_bits   = (uint8_t)len;
        s->little_endian = (order == 1);
        s->is_signed     = (sign == '-');
        s->scale         = scale;
        s->offset        = offset;
        if (got >= 10) snprintf(s->unit, sizeof s->unit, "%s", unit);
    }

    fclose(f);
    return n;
}

bool Dbc_Decode(const DbcSignal_t *sig, const CanRawFrame_t *frame, double *value_out)
{
    if (!sig || !frame || !value_out) return false;
    if (sig->can_id != frame->id) return false;

    int total_bits = frame->dlc * 8;
    uint64_t raw = 0;

    if (sig->little_endian) {
        /* Intel: the signal runs upward from start_bit, LSB first. */
        if (sig->start_bit + sig->length_bits > total_bits) return false;
        for (int k = 0; k < sig->length_bits; k++)
            raw |= (uint64_t)get_bit(frame->data, sig->start_bit + k) << k;
    } else {
        /* Motorola: start_bit is the MSB. Walk down inside the current
         * byte, then jump to the top bit of the NEXT byte. */
        int pos = sig->start_bit;
        for (int k = 0; k < sig->length_bits; k++) {
            if (pos < 0 || pos >= total_bits) return false;
            raw = (raw << 1) | (uint64_t)get_bit(frame->data, pos);
            if ((pos & 7) == 0) pos += 15; else pos -= 1;
        }
    }

    double value;
    if (sig->is_signed && sig->length_bits < 64 &&
        (raw >> (sig->length_bits - 1)) & 1) {
        /* Two's complement: subtract 2^len to get the negative value. */
        value = (double)raw - (double)((uint64_t)1 << sig->length_bits);
    } else {
        value = (double)raw;
    }

    *value_out = value * sig->scale + sig->offset;
    return true;
}

int Can_ReadLog(const char *path, CanRawFrame_t *out, int max_frames)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    char line[256];
    int n = 0;

    while (fgets(line, sizeof line, f) && n < max_frames) {
        double ts;
        char iface[16], payload[32];
        unsigned int id;

        if (sscanf(line, " (%lf) %15s %x#%31s", &ts, iface, &id, payload) != 4)
            continue;

        CanRawFrame_t *fr = &out[n];
        memset(fr, 0, sizeof *fr);
        fr->id = id;
        fr->timestamp_us = (uint64_t)(ts * 1e6);

        /* Payload is hex, two characters per byte. An odd character count
         * means a truncated log line, so drop the dangling nibble. */
        size_t hexlen = strlen(payload);
        size_t bytes  = hexlen / 2;
        if (bytes > 8) bytes = 8;
        for (size_t b = 0; b < bytes; b++) {
            char pair[3] = { payload[b * 2], payload[b * 2 + 1], '\0' };
            fr->data[b] = (uint8_t)strtoul(pair, NULL, 16);
        }
        fr->dlc = (uint8_t)bytes;
        n++;
    }

    fclose(f);
    return n;
}
