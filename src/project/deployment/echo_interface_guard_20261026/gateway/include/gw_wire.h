#ifndef GW_WIRE_H
#define GW_WIRE_H
/* Wire-format helpers shared by both servers and the spool:
 *  - SMC1 event file container (PROTOCOL.md 5.8)
 *  - 32-byte PCM records (5.5)
 *  - RESULT_WORDS32 consistency (5.6)
 *  - SMA1 frame append (5.1)
 * Nothing here is allowed to re-define the frozen constants from
 * interfaces/pc_backend_v1/c/sixmic_analysis_wire.h; it includes that header. */
#include <stdint.h>
#include <stddef.h>

#include "gw_util.h"
#include "sixmic_analysis_wire.h"
#include "sixmic_host.h" /* SM_R_* protocol-3 result word indices (frozen host enum) */

#define GW_SMC1_MAGIC_0 'S'
#define GW_SMC1_MAGIC_1 'M'
#define GW_SMC1_MAGIC_2 'C'
#define GW_SMC1_MAGIC_3 '1'
#define GW_SMC1_VERSION 1u
#define GW_SMC1_HEADER_BYTES 64u
#define GW_SMC1_RECORD_BYTES 32u

/* SMC1 flags (PROTOCOL.md 5.8 header word at offset 16). */
#define GW_SMC1_FLAG_INCOMPLETE     0x00000001u
#define GW_SMC1_FLAG_LOST_EVENTS    0x00000002u
#define GW_SMC1_FLAG_SUMMARY_STALE  0x00000004u
#define GW_SMC1_FLAG_ENV_INVALID    0x00000008u
#define GW_SMC1_FLAG_POSE_INVALID   0x00000010u

typedef struct {
    uint32_t flags;
    uint32_t clip_reason;
    uint64_t event_id;
    uint64_t first_sample;
    uint64_t last_sample;
    uint64_t record_count;
    uint32_t sample_rate_word; /* IEEE-754 float32 bits of the real sample rate */
} gw_smc1;

void gw_smc1_init(gw_smc1 *h);
void gw_smc1_encode(const gw_smc1 *h, uint8_t out[GW_SMC1_HEADER_BYTES]);
/* Returns 0 on a well-formed container header, negative otherwise. */
int gw_smc1_decode(const uint8_t in[GW_SMC1_HEADER_BYTES], gw_smc1 *h);

/* Encodes one 32-byte record: six sign-extended 24-bit samples as LE int32
 * (the fourth byte is the sign-extension byte) then the u64 sample index stored
 * low word first. sample_index must be contiguous across a payload. */
void gw_pcm_encode_record(const int32_t samples[SMA_PCM_CHANNELS],
                          uint64_t sample_index,
                          uint8_t out[SMA_PCM_RECORD_BYTES]);
int gw_pcm_decode_record(const uint8_t in[SMA_PCM_RECORD_BYTES],
                         int32_t samples[SMA_PCM_CHANNELS],
                         uint64_t *sample_index);
/* Checks framing (multiple of 32, non-empty) and per-record sample-index +1
 * continuity. Returns 0 or negative. */
int gw_pcm_validate_payload(const uint8_t *payload, uint32_t bytes,
                            uint64_t *first_sample_index, uint32_t *record_count);

/* Result snapshot sanity: word0 protocol must be 3. */
int gw_result_words_check(const uint32_t words[SMA_RESULT_WORD_COUNT]);
uint32_t gw_result_frame_id(const uint32_t words[SMA_RESULT_WORD_COUNT]);
uint32_t gw_result_config_version(const uint32_t words[SMA_RESULT_WORD_COUNT]);
/* Header fields of a RESULT_WORDS32 frame must equal payload words 2/3. */
int gw_result_header_matches(uint32_t header_frame_id, uint32_t header_config,
                             const uint32_t words[SMA_RESULT_WORD_COUNT]);

/* Appends one complete SMA1 frame (64-byte header + payload) to a FIFO.
 * Returns 1 when written, 0 when the FIFO lacks space (nothing written). */
int gw_binary_append_frame(gw_fifo *out, const sma_header *h,
                           const uint8_t *payload);

#endif