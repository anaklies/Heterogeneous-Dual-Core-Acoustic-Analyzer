#ifndef SIXMIC_ANALYSIS_PACKET_V2_H
#define SIXMIC_ANALYSIS_PACKET_V2_H
#include <stdint.h>
// Wire format is explicitly little-endian, field-by-field, not sizeof(struct).
// Payload floats use IEEE754 binary32. Consumers reject unknown required flags.
#define SIXMIC_PROTOCOL_VERSION 2u
#define SIXMIC_MAILBOX_BASE 0x43C20000u
#define SIXMIC_ANALYSIS_BASE 0x44A30000u
#define SIXMIC_FFT_BASE 0x44A40000u
#define SIXMIC_REMOVED_DOA_BIT (UINT64_C(1)<<8)
enum sixmic_status {SIXMIC_OK=0,SIXMIC_BAD_CONFIG=1,SIXMIC_STALE=2,
    SIXMIC_GAP=3,SIXMIC_OVERFLOW=4,SIXMIC_DMA_ERROR=5,SIXMIC_TIMEOUT=6,
    SIXMIC_UNSUPPORTED=7,SIXMIC_NOT_ACCEPTED=8};
enum sixmic_payload {SIXMIC_LEVELS=1,SIXMIC_SPECTRUM=2,SIXMIC_BANDS=3,
    SIXMIC_CROSS=4,SIXMIC_EVENT=5,SIXMIC_ROOM=6,SIXMIC_MANUAL_DAS=7};
struct sixmic_result_descriptor {
    uint32_t protocol_version, algorithm_version, session_id, config_generation;
    uint64_t sequence, first_sample;
    uint32_t sample_count, sample_rate, payload_type, payload_bytes;
    uint32_t payload_offset, status, error_flags, valid;
};
// Producers publish valid only after successful DMA completion and ownership
// transfer. Consumers require session/config/sequence match and bounded lengths.
// There is no automatic DOA, trackId, XYZ or range capability in this profile.
#endif
