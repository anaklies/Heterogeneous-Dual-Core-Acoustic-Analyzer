#include "gw_wire.h"

#include <string.h>

void gw_smc1_init(gw_smc1 *h)
{
    memset(h, 0, sizeof *h);
}

static uint32_t smc1_crc(const uint8_t *p, size_t n)
{
    return sma_crc32(p, n);
}

void gw_smc1_encode(const gw_smc1 *h, uint8_t out[GW_SMC1_HEADER_BYTES])
{
    memset(out, 0, GW_SMC1_HEADER_BYTES);
    out[0] = GW_SMC1_MAGIC_0;
    out[1] = GW_SMC1_MAGIC_1;
    out[2] = GW_SMC1_MAGIC_2;
    out[3] = GW_SMC1_MAGIC_3;
    sma_put_u16(out + 4, (uint16_t)GW_SMC1_VERSION);
    sma_put_u16(out + 6, (uint16_t)GW_SMC1_HEADER_BYTES);
    sma_put_u32(out + 8, GW_SMC1_RECORD_BYTES);
    sma_put_u32(out + 12, SMA_PCM_CHANNELS);
    sma_put_u32(out + 16, h->flags);
    sma_put_u32(out + 20, h->clip_reason);
    sma_put_u64(out + 24, h->event_id);
    sma_put_u64(out + 32, h->first_sample);
    sma_put_u64(out + 40, h->last_sample);
    sma_put_u64(out + 48, h->record_count);
    sma_put_u32(out + 56, h->sample_rate_word);
    sma_put_u32(out + 60, smc1_crc(out, 56));
}

int gw_smc1_decode(const uint8_t in[GW_SMC1_HEADER_BYTES], gw_smc1 *h)
{
    if (!h) return -1;
    if (in[0] != 'S' || in[1] != 'M' || in[2] != 'C' || in[3] != '1') return -1;
    if (sma_get_u16(in + 4) != GW_SMC1_VERSION) return -2;
    if (sma_get_u16(in + 6) != GW_SMC1_HEADER_BYTES) return -3;
    if (sma_get_u32(in + 8) != GW_SMC1_RECORD_BYTES) return -4;
    if (sma_get_u32(in + 12) != SMA_PCM_CHANNELS) return -5;
    if (sma_get_u32(in + 60) != smc1_crc(in, 56)) return -6;
    h->flags = sma_get_u32(in + 16);
    h->clip_reason = sma_get_u32(in + 20);
    h->event_id = sma_get_u64(in + 24);
    h->first_sample = sma_get_u64(in + 32);
    h->last_sample = sma_get_u64(in + 40);
    h->record_count = sma_get_u64(in + 48);
    h->sample_rate_word = sma_get_u32(in + 56);
    return 0;
}

void gw_pcm_encode_record(const int32_t samples[SMA_PCM_CHANNELS],
                          uint64_t sample_index,
                          uint8_t out[SMA_PCM_RECORD_BYTES])
{
    unsigned c;
    memset(out, 0, SMA_PCM_RECORD_BYTES);
    for (c = 0; c < SMA_PCM_CHANNELS; c++) {
        uint32_t v = (uint32_t)samples[c];
        sma_put_u32(out + SMA_PCM_CHANNEL_OFFSET(c), v);
    }
    sma_put_u64(out + SMA_PCM_SAMPLE_INDEX_OFFSET, sample_index);
}

int gw_pcm_decode_record(const uint8_t in[SMA_PCM_RECORD_BYTES],
                         int32_t samples[SMA_PCM_CHANNELS],
                         uint64_t *sample_index)
{
    unsigned c;
    if (!in) return -1;
    for (c = 0; c < SMA_PCM_CHANNELS; c++) {
        uint32_t raw = (uint32_t)in[SMA_PCM_CHANNEL_OFFSET(c)] |
                       ((uint32_t)in[SMA_PCM_CHANNEL_OFFSET(c) + 1] << 8) |
                       ((uint32_t)in[SMA_PCM_CHANNEL_OFFSET(c) + 2] << 16);
        uint32_t v;
        if (raw & 0x800000u) raw |= 0xFF000000u; /* 24-bit sign extension */
        v = raw;
        if (in[SMA_PCM_CHANNEL_OFFSET(c) + 3] != (uint8_t)((v >> 24) & 0xFFu))
            return -2; /* fourth byte must be the sign extension byte */
        if (samples) samples[c] = (int32_t)v;
    }
    if (sample_index) *sample_index = sma_get_u64(in + SMA_PCM_SAMPLE_INDEX_OFFSET);
    return 0;
}

int gw_pcm_validate_payload(const uint8_t *payload, uint32_t bytes,
                            uint64_t *first_sample_index, uint32_t *record_count)
{
    uint32_t recs, i;
    uint64_t first = 0, cur = 0, prev = 0;
    if (!payload || bytes < SMA_PCM_RECORD_BYTES) return -1;
    if (bytes % SMA_PCM_RECORD_BYTES != 0u) return -2;
    recs = bytes / SMA_PCM_RECORD_BYTES;
    for (i = 0; i < recs; i++) {
        const uint8_t *r = payload + (size_t)i * SMA_PCM_RECORD_BYTES;
        uint64_t idx = sma_get_u64(r + SMA_PCM_SAMPLE_INDEX_OFFSET);
        if (i == 0) first = idx;
        else if (idx != prev + 1u) return -3;
        prev = idx;
        cur = idx;
    }
    (void)cur;
    if (first_sample_index) *first_sample_index = first;
    if (record_count) *record_count = recs;
    return 0;
}

int gw_result_words_check(const uint32_t words[SMA_RESULT_WORD_COUNT])
{
    if (!words) return -1;
    if (words[SM_R_PROTOCOL] != 3u) return -2;
    return 0;
}

uint32_t gw_result_frame_id(const uint32_t words[SMA_RESULT_WORD_COUNT])
{
    return words ? words[SM_R_FRAME] : 0u;
}

uint32_t gw_result_config_version(const uint32_t words[SMA_RESULT_WORD_COUNT])
{
    return words ? words[SM_R_CONFIG] : 0u;
}

int gw_result_header_matches(uint32_t header_frame_id, uint32_t header_config,
                             const uint32_t words[SMA_RESULT_WORD_COUNT])
{
    if (!words) return -1;
    if (header_frame_id != words[SM_R_FRAME]) return -1;
    if (header_config != words[SM_R_CONFIG]) return -1;
    return 0;
}

int gw_binary_append_frame(gw_fifo *out, const sma_header *h,
                           const uint8_t *payload)
{
    uint8_t hdr[SMA_BINARY_HEADER_BYTES];
    size_t need;
    if (!out || !h) return 0;
    need = SMA_BINARY_HEADER_BYTES + h->payload_bytes;
    if (gw_fifo_space(out) < need) return 0;
    sma_header_encode(hdr, h);
    gw_fifo_write(out, hdr, SMA_BINARY_HEADER_BYTES);
    if (h->payload_bytes && payload)
        gw_fifo_write(out, payload, h->payload_bytes);
    return 1;
}
