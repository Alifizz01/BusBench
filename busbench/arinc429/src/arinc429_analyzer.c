/* ARINC 429 word decoding.
 *
 * The bit fiddling is all in one place on purpose: the label reversal
 * and the odd parity rule are the two things people get wrong, and both
 * are one small function each. */

#include "arinc429_analyzer.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define DATA_SHIFT 10        /* ARINC bit 11 is bit 10 counting from zero */
#define DATA_BITS  19        /* ARINC bits 11 to 29, sign included */
#define DATA_MASK  0x7FFFFu
#define SIGN_BIT   0x40000u  /* bit 29, the top of the data field */

/* The label is transmitted most significant bit first while every other
 * field is least significant bit first. In a word held as a normal
 * integer that means the label byte comes out backwards. */
static uint8_t reverse_byte(uint8_t b)
{
    uint8_t r = 0;
    for (int i = 0; i < 8; i++) r = (uint8_t)((r << 1) | ((b >> i) & 1));
    return r;
}

static int popcount32(uint32_t v)
{
    int n = 0;
    while (v) { v &= v - 1; n++; }
    return n;
}

uint8_t Arinc429_GetLabel(uint32_t word) { return reverse_byte((uint8_t)(word & 0xFF)); }
uint8_t Arinc429_GetSdi(uint32_t word)   { return (uint8_t)((word >> 8) & 0x3); }
uint8_t Arinc429_GetSsm(uint32_t word)   { return (uint8_t)((word >> 29) & 0x3); }

bool Arinc429_CheckParity(uint32_t word)
{
    /* Odd parity: the whole 32 bit word, parity bit included, must have
     * an odd number of ones. An even count means a bit flipped in flight. */
    return (popcount32(word) & 1) == 1;
}

bool Arinc429_IsUsable(uint32_t word)
{
    return Arinc429_GetSsm(word) == ARINC_SSM_NORMAL_OPERATION;
}

uint32_t Arinc429_BuildWord(uint8_t label_octal, uint8_t sdi, int32_t raw_value,
                            uint8_t ssm, uint8_t data_bits)
{
    if (data_bits == 0 || data_bits > DATA_BITS) return 0;

    /* BNR data is left justified: the used bits sit at the top of the
     * field and the unused low bits are padding. */
    uint8_t pad = (uint8_t)(DATA_BITS - data_bits);
    int32_t field = raw_value * (int32_t)(1u << pad);

    uint32_t word = reverse_byte(label_octal);
    word |= (uint32_t)(sdi & 0x3) << 8;
    word |= ((uint32_t)field & DATA_MASK) << DATA_SHIFT;
    word |= (uint32_t)(ssm & 0x3) << 29;

    /* Set the parity bit so the total count of ones ends up odd. */
    if ((popcount32(word) & 1) == 0) word |= 0x80000000u;
    return word;
}

int LabelDict_Load(const char *path, LabelDictEntry_t *out, int max_entries)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    char line[256];
    int n = 0;

    while (fgets(line, sizeof line, f) && n < max_entries) {
        if (line[0] == '#' || line[0] == '\n') continue;

        char label[16], name[32], unit[8];
        double scale;
        unsigned int bits;

        if (sscanf(line, " %15[^,], %31[^,], %7[^,], %lf, %u",
                   label, name, unit, &scale, &bits) != 5)
            continue;
        if (bits == 0 || bits > DATA_BITS) continue;

        LabelDictEntry_t *e = &out[n++];
        memset(e, 0, sizeof *e);
        /* Labels are written in octal by everyone in avionics, so they
         * are read in octal here rather than silently as decimal. */
        e->label_octal = (uint8_t)strtoul(label, NULL, 8);
        snprintf(e->name, sizeof e->name, "%s", name);
        snprintf(e->unit, sizeof e->unit, "%s", unit);
        e->lsb_scale = scale;
        e->data_bits = (uint8_t)bits;
    }

    fclose(f);
    return n;
}

bool Arinc429_AnalyzeWord(uint32_t raw_word, const LabelDictEntry_t *dict, int dict_len,
                          char *name_out, char *unit_out, double *value_out)
{
    if (!dict || !value_out) return false;
    if (!Arinc429_CheckParity(raw_word)) return false;

    uint8_t label = Arinc429_GetLabel(raw_word);
    const LabelDictEntry_t *e = NULL;
    for (int i = 0; i < dict_len; i++)
        if (dict[i].label_octal == label) { e = &dict[i]; break; }
    if (!e) return false;

    int32_t field = (int32_t)((raw_word >> DATA_SHIFT) & DATA_MASK);
    /* Two's complement over the full 19 bit field, with bit 29 as sign. */
    if ((uint32_t)field & SIGN_BIT) field -= (int32_t)(SIGN_BIT << 1);

    /* Undo the left justification. The padding bits are zero, so this
     * division is exact and works for negative values too. */
    int32_t pad_divisor = (int32_t)(1u << (DATA_BITS - e->data_bits));

    if (name_out) strcpy(name_out, e->name);
    if (unit_out) strcpy(unit_out, e->unit);
    *value_out = (double)(field / pad_divisor) * e->lsb_scale;
    return true;
}

int Arinc429_ReadCapture(const char *path, uint32_t *out, int max_words)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;

    char line[64];
    int n = 0;

    while (fgets(line, sizeof line, f) && n < max_words) {
        if (line[0] == '#' || line[0] == '\n') continue;
        unsigned int word;
        if (sscanf(line, " %x", &word) == 1) out[n++] = word;
    }

    fclose(f);
    return n;
}
