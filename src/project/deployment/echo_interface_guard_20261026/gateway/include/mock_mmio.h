#ifndef GW_MOCK_MMIO_H
#define GW_MOCK_MMIO_H
/* Deterministic fake protocol-3 MMIO model mirroring
 * integration/control/runtime_control.sv and the instrument_top result words.
 * Used by --mock-fixture and by host tests. It is a SOFTWARE MODEL ONLY: it
 * proves gateway framing/handling, never physical hardware behavior. */
#include "mmio.h"

#define GW_MOCK_DDR_BASE 0x10000000u
#define GW_MOCK_DDR_BYTES 0x04000000u /* 64 MiB reserved-DDR fixture window */
#define GW_MOCK_SERVICE_MAX_WORDS 16384u

typedef struct mock_mmio mock_mmio;

mock_mmio *mock_mmio_create(void);
void mock_mmio_destroy(mock_mmio *m);
gw_mmio *mock_mmio_gw(mock_mmio *m);
uint8_t *mock_mmio_ddr(mock_mmio *m);
uint32_t mock_mmio_ddr_base(const mock_mmio *m);
uint32_t mock_mmio_ddr_bytes(const mock_mmio *m);

/* Push a fresh result snapshot (sets result IRQ and increments epoch). */
void mock_mmio_set_result_words(mock_mmio *m, const uint32_t words[32]);
/* snapshot flip modes: 0 stable, 1 epoch changes once (one retry succeeds),
 * 2 epoch changes on every read (sm_read_snapshot always SM_RETRY). */
void mock_mmio_set_snapshot_flip(mock_mmio *m, int mode);

/* Config model: a doorbell write latches the shadow; the next status read
 * applies it (active version = shadow word1) or rejects it once. */
void mock_mmio_set_reject_next_commit(mock_mmio *m, int on);
uint32_t mock_mmio_active_config(const mock_mmio *m);
uint32_t mock_mmio_config_applied_count(const mock_mmio *m);
uint32_t mock_mmio_config_rejected_count(const mock_mmio *m);

/* Service snapshot model (16-word publish header at output-64).
 * flip modes: 0 stable, 1 header changes once (one copy retry succeeds),
 * 2 header changes every attempt (sm_copy_service always SM_RETRY). */
void mock_mmio_set_service(mock_mmio *m, uint32_t output_byte_address,
                           const uint32_t header[16], const uint32_t *words,
                           uint32_t word_count);
void mock_mmio_set_service_flip(mock_mmio *m, int mode);

/* Inject one clip into bank 0/1 (clip words + raw 32-byte records placed at
 * words[1]+words[2] inside the fixture DDR window). */
int mock_mmio_inject_clip(mock_mmio *m, unsigned bank, const uint32_t words[16],
                          const uint8_t *records, uint32_t record_bytes);
uint32_t mock_mmio_clip_mask(const mock_mmio *m);
uint32_t mock_mmio_clip_released_count(const mock_mmio *m);
uint32_t mock_mmio_irq_writes(const mock_mmio *m);

#endif
