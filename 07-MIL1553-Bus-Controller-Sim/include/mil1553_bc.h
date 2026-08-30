#ifndef MIL1553_BC_H
#define MIL1553_BC_H
/* Project 7: MIL-STD-1553 Bus Controller Simulator.
 * Goal: unlike ARINC429 (broadcast, no arbitration), 1553 is centrally
 * controlled - ONE Bus Controller (BC) polls up to 31 Remote Terminals
 * (RT) in a fixed schedule ("major/minor frame"). Learn command word
 * encoding and the poll/response cycle.
 *
 * Command word, 16 bits:
 *   15 .. 11    10     9 .. 5        4 .. 0
 *   RT address  T/R    subaddress    word count or mode code
 *
 * Status word, 16 bits:
 *   15 .. 11    10  9  8   7 .. 5   4    3     2    1    0
 *   RT address  ME  I  SR  reserved BCR  BUSY  SSF  DBA  TF   */

#include <stdint.h>
#include <stdbool.h>

#define MIL1553_BROADCAST_ADDRESS 31   /* every RT listens, none answers */
#define MIL1553_MODE_SUBADDRESS_A  0   /* subaddress 0 and 31 mean the low */
#define MIL1553_MODE_SUBADDRESS_B 31   /* five bits are a mode code, not a count */

/* Mode codes worth implementing. */
#define MIL1553_MODE_TRANSMIT_STATUS 0x02
#define MIL1553_MODE_RESET_RT        0x08

/* Status word bits. */
#define MIL1553_STATUS_MESSAGE_ERROR   (1u << 10)
#define MIL1553_STATUS_SERVICE_REQUEST (1u << 8)
#define MIL1553_STATUS_BROADCAST_RCVD  (1u << 4)
#define MIL1553_STATUS_BUSY            (1u << 3)
#define MIL1553_STATUS_SUBSYSTEM_FLAG  (1u << 2)
#define MIL1553_STATUS_TERMINAL_FLAG   (1u << 0)

typedef struct {
    uint8_t  rt_address;   /* 0-31 */
    uint8_t  tr;            /* 1 = Transmit (RT->BC), 0 = Receive (BC->RT) */
    uint8_t  subaddress;    /* 0-31, selects which data the RT should use */
    uint8_t  word_count;    /* 1-32 (0 encodes as 32) */
} Mil1553CommandWord_t;

typedef struct {
    uint8_t  rt_address;
    bool     message_error;
    bool     busy;
    uint8_t  status_flags;
} Mil1553StatusWord_t;

/* Encodes a command word for transmission on the bus. */
uint16_t Mil1553_EncodeCommand(const Mil1553CommandWord_t *cmd);

/* added: the other direction, so encoding can be tested by round trip. */
void Mil1553_DecodeCommand(uint16_t raw, Mil1553CommandWord_t *out);

/* One BC transaction: send command, then either send or receive up to
 * 32 data words, then read the RT's status word. Returns false on
 * timeout or message error - the BC's job is to notice and retry. */
bool Mil1553_BcTransaction(const Mil1553CommandWord_t *cmd,
                            uint16_t *data_inout, uint8_t data_count,
                            Mil1553StatusWord_t *status_out);

/* Runs the fixed major/minor frame schedule (a list of transactions
 * executed at a defined rate) - the heart of a real 1553 BC. */
void Mil1553_RunSchedule(const Mil1553CommandWord_t *schedule, uint8_t count, uint32_t minor_frame_ms);

/* added: what the schedule run actually achieved. A BC that quietly
 * skips a failing RT is worse than one that reports it. */
typedef struct {
    uint32_t transactions;
    uint32_t retries;
    uint32_t failures;
} Mil1553Stats_t;

void Mil1553_GetStats(Mil1553Stats_t *out);
void Mil1553_ResetStats(void);

/* added: the simulated remote terminals, so the BC has a bus to poll.
 * An address with no RT connected is how a timeout gets reproduced. */
void Rt_Reset(void);
void Rt_Connect(uint8_t rt_address);
void Rt_Disconnect(uint8_t rt_address);
void Rt_SetBusy(uint8_t rt_address, bool busy);
void Rt_SetSubsystemFault(uint8_t rt_address, bool faulted);
void Rt_LoadSubaddress(uint8_t rt_address, uint8_t subaddress,
                       const uint16_t *words, uint8_t count);
uint8_t Rt_ReadSubaddress(uint8_t rt_address, uint8_t subaddress,
                          uint16_t *out, uint8_t cap);
uint32_t Rt_BroadcastCount(uint8_t rt_address);

#endif /* MIL1553_BC_H */
