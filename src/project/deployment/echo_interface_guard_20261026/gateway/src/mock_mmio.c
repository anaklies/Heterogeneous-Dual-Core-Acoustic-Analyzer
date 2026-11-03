#include "mock_mmio.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct mock_mmio {
    gw_mmio base;
    uint8_t *ddr;
    uint32_t shadow[32];
    uint32_t pending_words[32];
    uint32_t active_words[32];
    uint32_t active_config;
    uint32_t snapshot[32];
    uint64_t snapshot_epoch;
    uint32_t epoch_reads;
    int snapshot_flip;
    int status_pending;
    int apply_countdown;
    int reject_next;
    uint32_t result_irq;
    uint32_t cfg_irq;
    uint32_t faults;
    uint32_t clip_words[2][16];
    uint32_t clip_mask;
    uint32_t clip_id_latch;
    uint32_t clip_released;
    uint32_t irq_writes;
    uint32_t applied_count;
    uint32_t rejected_count;
    uint32_t service_addr;
    uint32_t service_hdr[16];
    uint32_t service_words[GW_MOCK_SERVICE_MAX_WORDS];
    uint32_t service_word_count;
    int service_flip;
    uint32_t service_hdr_reads;
};

static int mk_read32(void *ctx, uint32_t off, uint32_t *v)
{
    mock_mmio *m = (mock_mmio *)ctx;
    if (!m || !v || (off & 3u)) return 1;
    if (off >= 0x40u && off < 0x40u + 32u * 4u) {
        *v = m->shadow[(off - 0x40u) / 4u];
        return 0;
    }
    if (off >= 0x100u && off < 0x100u + 32u * 4u) {
        *v = m->snapshot[(off - 0x100u) / 4u];
        return 0;
    }
    if (off >= 0x200u && off < 0x280u) {
        unsigned bank = (off >= 0x240u) ? 1u : 0u;
        *v = m->clip_words[bank][(off & 0x3Fu) / 4u];
        return 0;
    }
    switch (off) {
    case 0x000: *v = 0x534D4132u; return 0;
    case 0x004: *v = 3u; return 0;
    case 0x008: *v = 0x82000001u; return 0;
    case 0x00C: *v = 0u; return 0;
    case 0x010: *v = 0u; return 0;
    case 0x014: *v = m->faults; return 0;
    case 0x018: {
        uint32_t out = (uint32_t)m->snapshot_epoch;
        m->epoch_reads++;
        if (m->snapshot_flip == 1 && m->epoch_reads == 2u) {
            m->snapshot_epoch++;
            out = (uint32_t)m->snapshot_epoch;
        } else if (m->snapshot_flip >= 2) {
            m->snapshot_epoch++;
            out = (uint32_t)m->snapshot_epoch;
        }
        *v = out;
        return 0;
    }
    case 0x01C: *v = m->active_config; return 0;
    case 0x020: {
        if (m->status_pending) {
            if (--m->apply_countdown <= 0) {
                m->status_pending = 0;
                if (m->reject_next) {
                    m->reject_next = 0;
                    m->rejected_count++;
                    m->faults |= 0x40000000u;
                } else {
                    memcpy(m->active_words, m->pending_words, sizeof m->active_words);
                    m->active_config = m->pending_words[1];
                    m->applied_count++;
                }
                m->cfg_irq = 1;
            }
        }
        *v = (m->status_pending ? 1u : 0u) | (m->result_irq ? 2u : 0u) |
             (m->cfg_irq ? 4u : 0u);
        return 0;
    }
    case 0x030: *v = m->clip_mask; return 0;
    default: return 1;
    }
}

static int mk_write32(void *ctx, uint32_t off, uint32_t value)
{
    mock_mmio *m = (mock_mmio *)ctx;
    if (!m || (off & 3u)) return 1;
    if (off >= 0x40u && off < 0x40u + 32u * 4u) {
        m->shadow[(off - 0x40u) / 4u] = value;
        return 0;
    }
    switch (off) {
    case 0x020:
        if (value != 1u || m->status_pending) return 1;
        memcpy(m->pending_words, m->shadow, sizeof m->pending_words);
        m->status_pending = 1;
        m->apply_countdown = 1;
        m->cfg_irq = 0;
        return 0;
    case 0x024:
        if (value & 1u) m->result_irq = 0;
        if (value & 2u) m->cfg_irq = 0;
        m->irq_writes++;
        return 0;
    case 0x02C:
        m->clip_id_latch = value;
        return 0;
    case 0x028: {
        unsigned bank;
        if ((value & 0xFFFFFFFCu) != 0u || !(value & 1u)) return 1;
        bank = (value & 2u) ? 1u : 0u;
        if (!(m->clip_mask & (1u << bank))) return 1;
        if (m->clip_words[bank][0] != m->clip_id_latch) return 1;
        m->clip_mask &= ~(1u << bank);
        m->clip_released++;
        return 0;
    }
    default: return 1;
    }
}

static void mk_barrier(void *ctx)
{
    (void)ctx;
    __sync_synchronize();
}

static int mk_mem_read(void *ctx, uint32_t addr, uint32_t *dst, uint32_t words)
{
    mock_mmio *m = (mock_mmio *)ctx;
    uint64_t end = (uint64_t)addr + (uint64_t)words * 4u;
    if (!m || !dst) return 1;
    if ((addr & 3u) || addr < GW_MOCK_DDR_BASE ||
        end > (uint64_t)GW_MOCK_DDR_BASE + GW_MOCK_DDR_BYTES) return 1;
    memcpy(dst, m->ddr + (addr - GW_MOCK_DDR_BASE), (size_t)words * 4u);
    return 0;
}

static int mk_private_write(void *ctx,uint32_t address,const uint32_t *words,uint32_t count){
    mock_mmio*m=ctx;uint32_t index;
    if(address<0x10000000u||address%4)return 1;
    index=(address-0x10000000u)/4;
    if(!((index>=524288u&&(uint64_t)index+count<=525312u)||(index>=528384u&&(uint64_t)index+count<=529408u)||(index>=532480u&&(uint64_t)index+count<=537600u)||(index>=540672u&&(uint64_t)index+count<=545792u)))return 1;
    memcpy(m->ddr+(address-0x10000000u),words,4*count);return 0;
}

static int mk_feature_write(void *ctx,uint32_t address,const uint32_t *words,uint32_t count){
    mock_mmio*m=ctx;uint32_t index;
    if(address<0x10000000u||address%4)return 1;
    index=(address-0x10000000u)/4;
    if(!((index>=1048576u&&(uint64_t)index+count<=4194304u)||(index>=525312u&&(uint64_t)index+count<=525376u)))return 1;
    memcpy(m->ddr+(address-0x10000000u),words,4*count);return 0;
}

static int mk_mem_invalidate(void *ctx, uint32_t addr, uint32_t bytes)
{
    mock_mmio *m = (mock_mmio *)ctx;
    uint64_t end = (uint64_t)addr + bytes;
    if (!m || bytes == 0 || (bytes & 3u)) return 1;
    if (addr < GW_MOCK_DDR_BASE ||
        end > (uint64_t)GW_MOCK_DDR_BASE + GW_MOCK_DDR_BYTES) return 1;
    if (m->service_addr && addr == m->service_addr - 64u && bytes == 64u) {
        uint32_t before = m->service_hdr[1];
        m->service_hdr_reads++;
        if (m->service_flip == 1 && m->service_hdr_reads == 2u)
            m->service_hdr[1]++;
        else if (m->service_flip >= 2 && (m->service_hdr_reads % 2u) == 0u)
            m->service_hdr[1]++;
        if (m->service_hdr[1] != before) {
            /* the mutated header must be what the CPU reads back */
            memcpy(m->ddr + (addr - GW_MOCK_DDR_BASE), m->service_hdr, 64u);
        }
    }
    return 0;
}

mock_mmio *mock_mmio_create(void)
{
    mock_mmio *m = (mock_mmio *)calloc(1, sizeof *m);
    if (!m) return NULL;
    m->ddr = (uint8_t *)calloc(1, GW_MOCK_DDR_BYTES);
    if (!m->ddr) { free(m); return NULL; }
    m->base.dev.ctx = m;
    m->base.dev.read = mk_read32;
    m->base.dev.write = mk_write32;
    m->base.dev.barrier = mk_barrier;
    m->base.mem.ctx = m;
    m->base.mem.read = mk_mem_read;
    m->base.write_private = mk_private_write;
    m->base.write_feature = mk_feature_write;
    m->base.mem.invalidate = mk_mem_invalidate;
    m->base.mem.barrier = mk_barrier;
    m->base.mem.reserved_low = GW_MOCK_DDR_BASE;
    m->base.mem.reserved_high = GW_MOCK_DDR_BASE + GW_MOCK_DDR_BYTES;
    m->base.ddr_phys_base = GW_MOCK_DDR_BASE;
    m->base.ddr_bytes = GW_MOCK_DDR_BYTES;
    return m;
}

void mock_mmio_destroy(mock_mmio *m)
{
    if (!m) return;
    free(m->ddr);
    free(m);
}

gw_mmio *mock_mmio_gw(mock_mmio *m) { return m ? &m->base : NULL; }
uint8_t *mock_mmio_ddr(mock_mmio *m) { return m ? m->ddr : NULL; }
uint32_t mock_mmio_ddr_base(const mock_mmio *m) { return m ? GW_MOCK_DDR_BASE : 0; }
uint32_t mock_mmio_ddr_bytes(const mock_mmio *m) { return m ? GW_MOCK_DDR_BYTES : 0; }

void mock_mmio_set_result_words(mock_mmio *m, const uint32_t words[32])
{
    if (!m || !words) return;
    memcpy(m->snapshot, words, sizeof m->snapshot);
    m->snapshot_epoch++;
    m->result_irq = 1;
}

void mock_mmio_set_snapshot_flip(mock_mmio *m, int mode)
{
    if (m) m->snapshot_flip = mode;
}

void mock_mmio_set_reject_next_commit(mock_mmio *m, int on)
{
    if (m) m->reject_next = on ? 1 : 0;
}

uint32_t mock_mmio_active_config(const mock_mmio *m) { return m ? m->active_config : 0; }
uint32_t mock_mmio_config_applied_count(const mock_mmio *m) { return m ? m->applied_count : 0; }
uint32_t mock_mmio_config_rejected_count(const mock_mmio *m) { return m ? m->rejected_count : 0; }
uint32_t mock_mmio_clip_mask(const mock_mmio *m) { return m ? m->clip_mask : 0; }
uint32_t mock_mmio_clip_released_count(const mock_mmio *m) { return m ? m->clip_released : 0; }
uint32_t mock_mmio_irq_writes(const mock_mmio *m) { return m ? m->irq_writes : 0; }

void mock_mmio_set_service(mock_mmio *m, uint32_t output_byte_address,
                           const uint32_t header[16], const uint32_t *words,
                           uint32_t word_count)
{
    if (!m || !header) return;
    m->service_addr = output_byte_address;
    memcpy(m->service_hdr, header, sizeof m->service_hdr);
    if (words && word_count) {
        if (word_count > GW_MOCK_SERVICE_MAX_WORDS)
            word_count = GW_MOCK_SERVICE_MAX_WORDS;
        memcpy(m->service_words, words, (size_t)word_count * 4u);
    }
    m->service_word_count = word_count;
    if (output_byte_address >= 64u) {
        uint32_t hdr_addr = output_byte_address - 64u;
        if (hdr_addr >= GW_MOCK_DDR_BASE &&
            hdr_addr + 64u <= GW_MOCK_DDR_BASE + GW_MOCK_DDR_BYTES)
            memcpy(m->ddr + (hdr_addr - GW_MOCK_DDR_BASE), m->service_hdr, 64u);
    }
    if (words && output_byte_address >= GW_MOCK_DDR_BASE) {
        uint64_t end = (uint64_t)output_byte_address + (uint64_t)word_count * 4u;
        if (end <= (uint64_t)GW_MOCK_DDR_BASE + GW_MOCK_DDR_BYTES)
            memcpy(m->ddr + (output_byte_address - GW_MOCK_DDR_BASE), m->service_words,
                   (size_t)word_count * 4u);
    }
}

void mock_mmio_set_service_flip(mock_mmio *m, int mode)
{
    if (!m) return;
    m->service_flip = mode;
    m->service_hdr_reads = 0;
}

int mock_mmio_inject_clip(mock_mmio *m, unsigned bank, const uint32_t words[16],
                          const uint8_t *records, uint32_t record_bytes)
{
    uint64_t addr, end;
    if (!m || !words || bank > 1) return -1;
    if (record_bytes == 0 || record_bytes > GW_MOCK_DDR_BYTES) return -1;
    addr = (uint64_t)words[1] + words[2];
    end = addr + record_bytes;
    if (addr < GW_MOCK_DDR_BASE ||
        end > (uint64_t)GW_MOCK_DDR_BASE + GW_MOCK_DDR_BYTES) return -1;
    if (records) memcpy(m->ddr + (addr - GW_MOCK_DDR_BASE), records, record_bytes);
    memcpy(m->clip_words[bank], words, 16u * 4u);
    m->clip_mask |= (1u << bank);
    return 0;
}
