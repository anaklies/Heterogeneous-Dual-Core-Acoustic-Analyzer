#ifndef GW_FAKE_MMIO_H
#define GW_FAKE_MMIO_H
/* Host-test fixture helpers. The protocol-3 fake MMIO register model itself is
 * src/mock_mmio.c, shared with the --mock-fixture gateway mode so tests exercise
 * the same model the CLI can run. These helpers only build fixture content. */
#include <stdint.h>
#include <stddef.h>

#include "gateway.h"
#include "mock_mmio.h"

typedef struct {
    gw *gateway;
    mock_mmio *mmio;
} fake_env;

void fake_default_config(gw_config *cfg);
/* Starts an in-process gateway on ephemeral ports against the fixture model.
 * spool_dir must be a writable path (created if missing). */
int fake_env_start(fake_env *env, const char *spool_dir);
void fake_env_stop(fake_env *env);

/* 32-word config that passes the gateway/RTL mirror validation, recording
 * enabled, two 16 MiB raw rings at 0x12000000 / 0x13000000. */
void fake_fill_config(uint32_t words[32], uint32_t session, uint32_t version);
void fake_fill_result_words(uint32_t words[32], uint32_t frame, uint32_t config,
                            uint32_t session, uint64_t sample_index);
void fake_fill_clip_words(uint32_t words[16], uint32_t event_id,
                          uint32_t bank_base, uint32_t frames,
                          uint64_t first_sample, uint32_t session,
                          uint32_t config);
/* Fills frames * 32 bytes of deterministic PCM records starting at first_sample. */
void fake_make_records(uint8_t *out, uint32_t frames, uint64_t first_sample);
void fake_fill_service_header(uint32_t hdr[16], uint32_t session,
                              uint32_t config, uint32_t length, uint32_t done);

#endif
