/* libFuzzer: Dbc_Decode with attacker-chosen signal geometry and frame.
 * The Motorola walk jumps between bytes; any out-of-bounds read is a bug. */
#include "can_sniffer.h"
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (size < 13) return 0;
    DbcSignal_t sig = {0};
    CanRawFrame_t frame = {0};
    sig.can_id = frame.id = 0x100;
    sig.start_bit = data[0];
    sig.length_bits = data[1];
    sig.little_endian = data[2] & 1;
    sig.is_signed = data[2] & 2;
    sig.scale = 1.0;
    frame.dlc = data[3] % 9;
    memcpy(frame.data, data + 4, 8);
    double value;
    (void)Dbc_Decode(&sig, &frame, &value);
    return 0;
}
