#ifndef ARINC429_ANALYZER_H
#define ARINC429_ANALYZER_H
/* Project 6: ARINC 429 Bus Analyzer (like project 1, but avionics-side).
 * Goal: capture raw 32-bit ARINC429 words off a bus (or a capture file)
 * and decode them using a label dictionary (the avionics equivalent of
 * a DBC file) into physical values with units.
 *
 * Word layout, using ARINC bit numbers 1 to 32:
 *
 *   32     31 30    29        29 .. 11        10 9      8 .. 1
 *   parity |  SSM  | sign |     data      |   SDI   |  label  |
 *
 * Two things catch everyone out:
 *   - the label is transmitted most significant bit first while every
 *     other field is least significant bit first, so the label byte on
 *     the wire is bit reversed
 *   - parity is ODD over all 32 bits, not even */

#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint8_t  label_octal;      /* e.g. 0203 for altitude on many systems */
    char     name[32];
    char     unit[8];
    double   lsb_scale;         /* value = raw_data * lsb_scale */
    uint8_t  data_bits;          /* how many of the 19 data bits are used */
} LabelDictEntry_t;

/* Sign/status matrix values for BNR data. Only Normal Operation carries
 * a number worth using; the other three say the source knows it cannot
 * give you one. */
#define ARINC_SSM_FAILURE_WARNING  0x0
#define ARINC_SSM_NO_COMPUTED_DATA 0x1
#define ARINC_SSM_FUNCTIONAL_TEST  0x2
#define ARINC_SSM_NORMAL_OPERATION 0x3

int   LabelDict_Load(const char *path, LabelDictEntry_t *out, int max_entries);

/* Decodes one captured 32-bit word using the dictionary, fills
 * name/unit/value; returns false if label not found or parity fails. */
bool  Arinc429_AnalyzeWord(uint32_t raw_word, const LabelDictEntry_t *dict, int dict_len,
                            char *name_out, char *unit_out, double *value_out);

/* added: the pieces AnalyzeWord is built from, useful on their own. */
uint8_t Arinc429_GetLabel(uint32_t word);     /* returns the octal label value */
uint8_t Arinc429_GetSdi(uint32_t word);
uint8_t Arinc429_GetSsm(uint32_t word);
bool    Arinc429_CheckParity(uint32_t word);

/* added: a word can decode perfectly and still be meaningless. Anything
 * other than Normal Operation means the source is telling you not to use
 * the number. AnalyzeWord still decodes it, so the caller has to ask. */
bool    Arinc429_IsUsable(uint32_t word);

/* added: builds a word, so the analyzer can be tested by round trip
 * rather than against hand written hex. */
uint32_t Arinc429_BuildWord(uint8_t label_octal, uint8_t sdi, int32_t raw_value,
                            uint8_t ssm, uint8_t data_bits);

/* added: reads a capture file of one hex word per line. */
int   Arinc429_ReadCapture(const char *path, uint32_t *out, int max_words);

#endif /* ARINC429_ANALYZER_H */
