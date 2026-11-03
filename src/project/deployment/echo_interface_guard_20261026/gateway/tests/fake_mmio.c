#include "fake_mmio.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void fake_default_config(gw_config *cfg)
{
    gw_config_defaults(cfg);
    cfg->mock_fixture = 1;
    snprintf(cfg->bind_addr, sizeof cfg->bind_addr, "%s", "127.0.0.1");
    cfg->control_port = 0;
    cfg->binary_port = 0;
    cfg->poll_ms = 1;
    cfg->max_binary_payload = 1048576;
    cfg->service_snapshot_addr = GW_MOCK_DDR_BASE + 0x00200000u;
    cfg->service_snapshot_words = 16;
    cfg->job_fixture_polls = 2;
    cfg->spool_limit_bytes = 8u * 1024u * 1024u;
    snprintf(cfg->spool_dir, sizeof cfg->spool_dir, "%s", "build/test_spool");
}

int fake_env_start(fake_env *env, const char *spool_dir)
{
    char err[512];
    memset(env, 0, sizeof *env);
    env->mmio = mock_mmio_create();
    if (!env->mmio) return -1;
    env->gateway = (gw *)calloc(1, sizeof(gw));
    if (!env->gateway) { mock_mmio_destroy(env->mmio); return -1; }
    {
        gw_config cfg;
        fake_default_config(&cfg);
        snprintf(cfg.spool_dir, sizeof cfg.spool_dir, "%s", spool_dir);
        if (gw_init(env->gateway, &cfg, mock_mmio_gw(env->mmio), err,
                    sizeof err) != 0) {
            fprintf(stderr, "FAKE_ENV_INIT_FAILED: %s\n", err);
            free(env->gateway);
            env->gateway = NULL;
            mock_mmio_destroy(env->mmio);
            env->mmio = NULL;
            return -1;
        }
    }
    return 0;
}

void fake_env_stop(fake_env *env)
{
    if (env->gateway) {
        gw_shutdown(env->gateway);
        free(env->gateway);
        env->gateway = NULL;
    }
    if (env->mmio) {
        mock_mmio_destroy(env->mmio);
        env->mmio = NULL;
    }
}

void fake_fill_config(uint32_t words[32], uint32_t session, uint32_t version)
{
    memset(words, 0, 32 * sizeof(uint32_t));
    words[SM_C_SESSION] = session;
    words[SM_C_VERSION] = version;
    words[SM_C_ARENA_BASE] = 0x10000000u;
    words[SM_C_ARENA_WORDS] = 4194304u;
    words[SM_C_RESERVED_LOW] = 0x10000000u;
    words[SM_C_RESERVED_HIGH] = 0x14000000u;
    words[SM_C_P1_DESCRIPTOR] = 524288u;
    words[SM_C_P2_DESCRIPTOR] = 524352u;
    words[SM_C_FLAGS] = SM_P1_ENABLE | SM_P2_ENABLE | SM_PAUSE_P1 | SM_RECORD_ENABLE;
    words[SM_C_BANK0] = 0x12000000u;
    words[SM_C_BANK_BYTES] = 0x01000000u;
    words[SM_C_RAW_LOW] = 0x12000000u;
    words[SM_C_RAW_HIGH] = 0x14000000u;
    words[SM_C_BANK1] = 0x13000000u;
    words[SM_C_EVENT_ARM] = 1u;
    words[SM_C_P1_LAST_INDEX] = 0u;
    words[SM_C_P1_STRIDE_WORDS] = 64u;
    words[SM_C_P2_ONESHOT] = 0u;
}

void fake_fill_result_words(uint32_t words[32], uint32_t frame, uint32_t config,
                            uint32_t session, uint64_t sample_index)
{
    memset(words, 0, 32 * sizeof(uint32_t));
    words[SM_R_PROTOCOL] = 3u;
    words[SM_R_ALGORITHM] = 0x82000002u;
    words[SM_R_FRAME] = frame;
    words[SM_R_CONFIG] = config;
    words[SM_R_SESSION] = session;
    words[SM_R_SLOT] = 0u;
    words[SM_R_FFT_BASE] = 0x00100000u;
    words[SM_R_CYCLES] = 123456u;
    words[SM_R_SAMPLE_LOW] = (uint32_t)(sample_index & 0xFFFFFFFFu);
    words[SM_R_SAMPLE_HIGH] = (uint32_t)(sample_index >> 32);
    words[SM_R_FAULTS] = 0u;
    words[SM_R_MIC_STATUS] = 0x3Fu;
    words[SM_R_TEMP_CENTI] = (uint32_t)2530;
    words[SM_R_HUMIDITY] = 4000u;
    words[SM_R_PRESSURE_PA] = 101325u;
    words[SM_R_SOUND_SPEED_FLOAT] = 0x42F2E0A4u;
    words[SM_R_SENSOR_VALID] = 0xFu;
    words[SM_R_SAMPLE_RATE_FLOAT] = 0x473B89C6u; /* 48009.775390625 Hz */
}

void fake_fill_clip_words(uint32_t words[16], uint32_t event_id,
                          uint32_t bank_base, uint32_t frames,
                          uint64_t first_sample, uint32_t session,
                          uint32_t config)
{
    memset(words, 0, 16 * sizeof(uint32_t));
    words[SM_E_ID] = event_id;
    words[SM_E_BASE] = bank_base;
    words[SM_E_OFFSET] = 0u;
    words[SM_E_FRAMES] = frames;
    words[SM_E_FIRST_LOW] = (uint32_t)(first_sample & 0xFFFFFFFFu);
    words[SM_E_FIRST_HIGH] = (uint32_t)(first_sample >> 32);
    words[SM_E_LAST_LOW] = (uint32_t)((first_sample + frames - 1u) & 0xFFFFFFFFu);
    words[SM_E_LAST_HIGH] = (uint32_t)((first_sample + frames - 1u) >> 32);
    words[SM_E_INCOMPLETE] = 0u;
    words[SM_E_SESSION] = session;
    words[SM_E_CONFIG] = config;
    words[SM_E_REASON] = 3u;
    words[SM_E_PRE_Q22] = 1000u;
    words[SM_E_POST_Q22] = 2000u;
    words[SM_E_DELTA_Q22] = 1000u;
    words[SM_E_AGE_VALID] = 0x80000000u | 42u;
}

void fake_make_records(uint8_t *out, uint32_t frames, uint64_t first_sample)
{
    uint32_t f;
    for (f = 0; f < frames; f++) {
        int32_t samples[6];
        unsigned c;
        for (c = 0; c < 6; c++) {
            int32_t v = (int32_t)((f * 37u + c * 11u) % 100000u) - 50000;
            if (c == 0 && f == 0) v = -8388608;   /* most negative 24-bit */
            if (c == 1 && f == 0) v = 8388607;    /* most positive 24-bit */
            if (c == 2 && f == 0) v = -1;
            samples[c] = v;
        }
        gw_pcm_encode_record(samples, first_sample + f,
                             out + (size_t)f * GW_SMC1_RECORD_BYTES);
    }
}

void fake_fill_service_header(uint32_t hdr[16], uint32_t session,
                              uint32_t config, uint32_t length, uint32_t done)
{
    memset(hdr, 0, 16 * sizeof(uint32_t));
    hdr[0] = 0x52534C54u;
    hdr[1] = 7u;            /* commitSequence */
    hdr[2] = session;
    hdr[3] = config;
    hdr[4] = 1u;            /* generation */
    hdr[5] = 1u;            /* programVersion */
    hdr[6] = 42u;           /* sourceFrame */
    hdr[7] = 0x11u;         /* sampleIndexLow */
    hdr[8] = 0x22u;         /* sampleIndexHigh */
    hdr[9] = 0u;
    hdr[10] = length;
    hdr[11] = 0u;
    hdr[12] = 0u;
    hdr[13] = 0x100u;
    hdr[14] = done;
    hdr[15] = 0u;
}
