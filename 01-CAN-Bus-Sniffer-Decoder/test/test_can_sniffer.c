/* Self-check and demo in one. Run it and you see the decoded bus;
 * if the bit maths ever breaks, an assert fires instead. */

#include "can_sniffer.h"
#include <stdio.h>
#include <assert.h>
#include <math.h>
#include <string.h>

static int close_to(double a, double b) { return fabs(a - b) < 1e-6; }

static const DbcSignal_t *find(const DbcSignal_t *sigs, int n, const char *name)
{
    for (int i = 0; i < n; i++)
        if (strcmp(sigs[i].name, name) == 0) return &sigs[i];
    return NULL;
}

int main(void)
{
    DbcSignal_t sigs[32];
    CanRawFrame_t frames[64];

    int nsig = Dbc_Load("data/example.dbc", sigs, 32);
    int nfrm = Can_ReadLog("data/example.log", frames, 64);
    printf("loaded %d signals, %d frames\n\n", nsig, nfrm);
    assert(nsig == 5);
    assert(nfrm == 4);

    /* The parser has to pick up endianness and sign from "@0-" style flags. */
    const DbcSignal_t *ang = find(sigs, nsig, "SteeringAngle");
    assert(ang && !ang->little_endian && ang->is_signed);
    const DbcSignal_t *rpm = find(sigs, nsig, "EngineSpeed");
    assert(rpm && rpm->little_endian && !rpm->is_signed);

    double v;

    /* Intel layout, straight scaling. */
    assert(Dbc_Decode(rpm, &frames[0], &v) && close_to(v, 2000.0));
    /* Intel layout with an offset, the classic temperature-minus-40 case. */
    assert(Dbc_Decode(find(sigs, nsig, "CoolantTemp"), &frames[0], &v) && close_to(v, 90.0));
    /* Motorola layout, bits walk the other way. */
    assert(Dbc_Decode(find(sigs, nsig, "VehicleSpeed"), &frames[1], &v) && close_to(v, 100.0));
    /* Motorola AND signed, so the raw value needs sign extension. */
    assert(Dbc_Decode(ang, &frames[1], &v) && close_to(v, -45.0));
    /* A signal only decodes from its own CAN ID. */
    assert(!Dbc_Decode(rpm, &frames[1], &v));

    for (int f = 0; f < nfrm; f++) {
        printf("[%llu us] ID 0x%03X:\n", (unsigned long long)frames[f].timestamp_us, frames[f].id);
        for (int s = 0; s < nsig; s++)
            if (Dbc_Decode(&sigs[s], &frames[f], &v))
                printf("    %-14s %10.2f %s\n", sigs[s].name, v, sigs[s].unit);
    }

    printf("\nall assertions passed\n");
    return 0;
}
