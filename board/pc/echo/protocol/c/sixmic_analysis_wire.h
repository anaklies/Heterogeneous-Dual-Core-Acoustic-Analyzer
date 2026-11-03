/* sixmic_analysis_wire.h -- sixmic-analysis v1 frozen wire constants.
 *
 * Interface: interfaces/pc_backend_v1/PROTOCOL.md (frozen 2026-10-24).
 * Role: shared by the PC backend (Python mirrors these values) and the PS
 *       Ethernet gateway candidate (deployment/ps_analysis_gateway/).
 *
 * RULES
 *  - Do not renumber message types or move header fields without a version bump.
 *  - All binary fields are explicitly encoded little-endian; never memcpy a
 *    compiler struct onto the wire.
 *  - This header is standalone C99 and contains no DSP or device access.
 */
#ifndef SIXMIC_ANALYSIS_WIRE_H
#define SIXMIC_ANALYSIS_WIRE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SMA_PROTOCOL_NAME "sixmic-analysis"
#define SMA_PROTOCOL_VERSION 1u
#define SMA_DEFAULT_CONTROL_PORT 48120u
#define SMA_DEFAULT_BINARY_PORT 48121u

/* Control channel (UTF-8 JSON Lines over TCP). */
#define SMA_MAX_LINE_BYTES 65536u          /* including the terminating LF */
#define SMA_MAX_REQUEST_ID_BYTES 64u
#define SMA_MAX_SESSION_ID_BYTES 64u
#define SMA_MAX_JSON_DEPTH 32u
#define SMA_DEFAULT_MAX_PENDING_JOBS 64u
#define SMA_DUPLICATE_CACHE_ENTRIES 256u
#define SMA_DUPLICATE_CACHE_SECONDS 120u

/* Binary channel (SMA1 framed TCP). */
#define SMA_BINARY_MAGIC0 'S'
#define SMA_BINARY_MAGIC1 'M'
#define SMA_BINARY_MAGIC2 'A'
#define SMA_BINARY_MAGIC3 '1'
#define SMA_BINARY_PROTOCOL_VERSION 1u
#define SMA_BINARY_HEADER_BYTES 64u
#define SMA_DEFAULT_MAX_BINARY_PAYLOAD 1048576u  /* 1 MiB */
#define SMA_MIN_MAX_BINARY_PAYLOAD 4096u
#define SMA_MAX_MAX_BINARY_PAYLOAD 16777216u     /* 16 MiB negotiated ceiling */

/* Raw PCM record: 6 x sign-extended 24-bit LE int32, then uint64 sample index
 * stored low word first. 32 bytes per record. Never 24 bytes and never float. */
#define SMA_PCM_RECORD_BYTES 32u
#define SMA_PCM_CHANNELS 6u
#define SMA_PCM_SAMPLE_INDEX_OFFSET 24u  /* 6 * 4 */
#define SMA_PCM_CHANNEL_OFFSET(c) (4u * (c))

/* RESULT_WORDS32 payload is exactly the 32-word protocol-3 result snapshot. */
#define SMA_RESULT_WORD_COUNT 32u
#define SMA_RESULT_PAYLOAD_BYTES (4u * SMA_RESULT_WORD_COUNT)

/* SERVICE_SNAPSHOT payload: 16-word publish header + service words. */
#define SMA_SERVICE_HEADER_WORDS 16u
#define SMA_SERVICE_HEADER_BYTES 64u

/* Message types (u16). Frozen numbering. */
typedef enum {
    SMA_MSG_HELLO             = 0x0001, /* client -> server: JSON registration payload */
    SMA_MSG_HELLO_ACK         = 0x0002, /* server -> client: JSON accepted payload */
    SMA_MSG_STREAM_SCHEMA     = 0x0003, /* server -> client: JSON stream description, always first */
    SMA_MSG_PCM_RECORD32      = 0x0004, /* server -> client: N * 32-byte raw PCM records */
    SMA_MSG_RESULT_WORDS32    = 0x0005, /* server -> client: 32 x u32 LE result snapshot */
    SMA_MSG_SERVICE_SNAPSHOT  = 0x0006, /* server -> client: 16-word header + service words */
    SMA_MSG_EVENT_FILE_CHUNK  = 0x0007, /* server -> client: byte range of one event file */
    SMA_MSG_STREAM_GAP        = 0x0008, /* server -> client: JSON explicit gap/loss record */
    SMA_MSG_HEARTBEAT         = 0x0009, /* both directions: empty payload keepalive */
    SMA_MSG_BYE               = 0x000A, /* both directions: JSON reason, then close */
    SMA_MSG_ERROR             = 0x000B  /* server -> client: JSON fatal error, then close */
} sma_message_type;

/* Header flags (u16). Unknown bits are ignored by receivers but recorded;
 * senders must write 0 for all reserved bits. */
typedef enum {
    SMA_FLAG_CRC32_VALID           = 1u << 0, /* payloadCRC32 covers the payload */
    SMA_FLAG_GAP_BEFORE            = 1u << 1, /* a gap/loss precedes this frame for its stream */
    SMA_FLAG_LAST_CHUNK            = 1u << 2, /* final chunk of a transferred file */
    SMA_FLAG_FIRST_CHUNK           = 1u << 3, /* first chunk of a transferred file */
    SMA_FLAG_DEVICE_MONOTONIC_VALID= 1u << 4, /* deviceMonotonicNs is a real device time */
    SMA_FLAG_SAMPLE_INDEX_VALID    = 1u << 5  /* firstSampleIndex is meaningful for this frame */
} sma_header_flag;

#define SMA_FLAGS_KNOWN_MASK 0x003Fu
#define SMA_FLAGS_RESERVED_MASK 0xFFC0u

/* Explicit little-endian field offsets inside the 64-byte header. */
enum sma_header_offset {
    SMA_HDR_OFF_MAGIC              = 0,  /* u8[4] 'SMA1' */
    SMA_HDR_OFF_PROTOCOL_VERSION   = 4,  /* u16 */
    SMA_HDR_OFF_HEADER_BYTES       = 6,  /* u16, must be 64 */
    SMA_HDR_OFF_MESSAGE_TYPE       = 8,  /* u16 */
    SMA_HDR_OFF_FLAGS              = 10, /* u16 */
    SMA_HDR_OFF_PAYLOAD_BYTES      = 12, /* u32 */
    SMA_HDR_OFF_STREAM_ID          = 16, /* u32, 0 for connection-level frames */
    SMA_HDR_OFF_SEQUENCE           = 20, /* u32, per stream, wraps mod 2^32 */
    SMA_HDR_OFF_CONNECTION_EPOCH   = 24, /* u64 */
    SMA_HDR_OFF_FIRST_SAMPLE_INDEX = 32, /* u64 */
    SMA_HDR_OFF_DEVICE_TIME_NS     = 40, /* u64, 0 when time is unknown */
    SMA_HDR_OFF_FRAME_ID           = 48, /* u32 */
    SMA_HDR_OFF_CONFIG_VERSION     = 52, /* u32 */
    SMA_HDR_OFF_PAYLOAD_CRC32      = 56, /* u32 IEEE reflected CRC-32 of payload */
    SMA_HDR_OFF_RESERVED           = 60  /* u32, must be 0 */
};

typedef struct {
    uint16_t protocol_version;
    uint16_t header_bytes;
    uint16_t message_type;
    uint16_t flags;
    uint32_t payload_bytes;
    uint32_t stream_id;
    uint32_t sequence;
    uint64_t connection_epoch;
    uint64_t first_sample_index;
    uint64_t device_monotonic_ns;
    uint32_t frame_id;
    uint32_t config_version;
    uint32_t payload_crc32;
} sma_header;

/* CRC-32/IEEE reflected: polynomial 0xEDB88320, init 0xFFFFFFFF, xorout 0xFFFFFFFF.
 * sma_crc32_update() is the incremental primitive (pass 0xFFFFFFFF to start);
 * sma_crc32() is the one-shot wire CRC. */
static inline uint32_t sma_crc32_update(uint32_t crc, const uint8_t *data, size_t bytes)
{
    size_t i;
    for (i = 0; i < bytes; ++i) {
        unsigned bit;
        crc ^= data[i];
        for (bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1u)));
    }
    return crc;
}

static inline uint32_t sma_crc32(const uint8_t *data, size_t bytes)
{
    return sma_crc32_update(0xFFFFFFFFu, data, bytes) ^ 0xFFFFFFFFu;
}

static inline void sma_put_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)(v >> 8);
}
static inline void sma_put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
    p[2] = (uint8_t)((v >> 16) & 0xFFu);
    p[3] = (uint8_t)((v >> 24) & 0xFFu);
}
static inline void sma_put_u64(uint8_t *p, uint64_t v)
{
    sma_put_u32(p, (uint32_t)(v & 0xFFFFFFFFu));
    sma_put_u32(p + 4, (uint32_t)(v >> 32));
}
static inline uint16_t sma_get_u16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}
static inline uint32_t sma_get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static inline uint64_t sma_get_u64(const uint8_t *p)
{
    return (uint64_t)sma_get_u32(p) | ((uint64_t)sma_get_u32(p + 4) << 32);
}

/* Encode a header. payload_crc32 in the struct is written as given; use
 * sma_header_encode_payload() when the payload buffer is available. */
static inline void sma_header_encode(uint8_t out[SMA_BINARY_HEADER_BYTES], const sma_header *h)
{
    out[SMA_HDR_OFF_MAGIC + 0] = SMA_BINARY_MAGIC0;
    out[SMA_HDR_OFF_MAGIC + 1] = SMA_BINARY_MAGIC1;
    out[SMA_HDR_OFF_MAGIC + 2] = SMA_BINARY_MAGIC2;
    out[SMA_HDR_OFF_MAGIC + 3] = SMA_BINARY_MAGIC3;
    sma_put_u16(out + SMA_HDR_OFF_PROTOCOL_VERSION, h->protocol_version);
    sma_put_u16(out + SMA_HDR_OFF_HEADER_BYTES, h->header_bytes);
    sma_put_u16(out + SMA_HDR_OFF_MESSAGE_TYPE, h->message_type);
    sma_put_u16(out + SMA_HDR_OFF_FLAGS, h->flags);
    sma_put_u32(out + SMA_HDR_OFF_PAYLOAD_BYTES, h->payload_bytes);
    sma_put_u32(out + SMA_HDR_OFF_STREAM_ID, h->stream_id);
    sma_put_u32(out + SMA_HDR_OFF_SEQUENCE, h->sequence);
    sma_put_u64(out + SMA_HDR_OFF_CONNECTION_EPOCH, h->connection_epoch);
    sma_put_u64(out + SMA_HDR_OFF_FIRST_SAMPLE_INDEX, h->first_sample_index);
    sma_put_u64(out + SMA_HDR_OFF_DEVICE_TIME_NS, h->device_monotonic_ns);
    sma_put_u32(out + SMA_HDR_OFF_FRAME_ID, h->frame_id);
    sma_put_u32(out + SMA_HDR_OFF_CONFIG_VERSION, h->config_version);
    sma_put_u32(out + SMA_HDR_OFF_PAYLOAD_CRC32, h->payload_crc32);
    sma_put_u32(out + SMA_HDR_OFF_RESERVED, 0u);
}

/* Decode and validate the immutable header fields. Returns 0 on success and a
 * negative value on a frame that must terminate the connection. */
static inline int sma_header_decode(const uint8_t in[SMA_BINARY_HEADER_BYTES],
                                    sma_header *h, uint32_t negotiated_max_payload)
{
    if (!h) return -1;
    if (in[0] != 'S' || in[1] != 'M' || in[2] != 'A' || in[3] != '1') return -2;
    h->protocol_version = sma_get_u16(in + SMA_HDR_OFF_PROTOCOL_VERSION);
    h->header_bytes = sma_get_u16(in + SMA_HDR_OFF_HEADER_BYTES);
    h->message_type = sma_get_u16(in + SMA_HDR_OFF_MESSAGE_TYPE);
    h->flags = sma_get_u16(in + SMA_HDR_OFF_FLAGS);
    h->payload_bytes = sma_get_u32(in + SMA_HDR_OFF_PAYLOAD_BYTES);
    h->stream_id = sma_get_u32(in + SMA_HDR_OFF_STREAM_ID);
    h->sequence = sma_get_u32(in + SMA_HDR_OFF_SEQUENCE);
    h->connection_epoch = sma_get_u64(in + SMA_HDR_OFF_CONNECTION_EPOCH);
    h->first_sample_index = sma_get_u64(in + SMA_HDR_OFF_FIRST_SAMPLE_INDEX);
    h->device_monotonic_ns = sma_get_u64(in + SMA_HDR_OFF_DEVICE_TIME_NS);
    h->frame_id = sma_get_u32(in + SMA_HDR_OFF_FRAME_ID);
    h->config_version = sma_get_u32(in + SMA_HDR_OFF_CONFIG_VERSION);
    h->payload_crc32 = sma_get_u32(in + SMA_HDR_OFF_PAYLOAD_CRC32);
    if (h->protocol_version != SMA_BINARY_PROTOCOL_VERSION) return -3;
    if (h->header_bytes != SMA_BINARY_HEADER_BYTES) return -4;
    if (sma_get_u32(in + SMA_HDR_OFF_RESERVED) != 0u) return -5;
    if (h->payload_bytes > negotiated_max_payload) return -6;
    /* HEARTBEAT is empty; BYE carries an optional UTF-8 JSON {"reason":...}
     (PROTOCOL.md 5.3), so only HEARTBEAT is payload-free. */
    if (h->payload_bytes != 0u && h->message_type == SMA_MSG_HEARTBEAT)
        return -7;
    if (h->message_type != SMA_MSG_HEARTBEAT &&
        h->message_type != SMA_MSG_HELLO &&
        h->payload_bytes == 0u)
        return -8;
    return 0;
}

/* Big-endian helpers are deliberately absent: SMA never uses big-endian fields. */

#ifdef __cplusplus
}
#endif

#endif /* SIXMIC_ANALYSIS_WIRE_H */
