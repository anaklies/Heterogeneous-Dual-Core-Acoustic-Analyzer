#ifndef SIXMIC_HOST_H
#define SIXMIC_HOST_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Offsets are relative to the instrument HOST window (board draft 0x43c20000).
 * Serialize every API call with one controller mutex. Callbacks must complete
 * device accesses and report AXI errors; volatile alone is not a barrier. */
typedef int (*sm_read32)(void *ctx, uint32_t offset, uint32_t *value);
typedef int (*sm_write32)(void *ctx, uint32_t offset, uint32_t value);
typedef void (*sm_barrier)(void *ctx);
typedef struct { void *ctx; sm_read32 read; sm_write32 write; sm_barrier barrier; } sm_device;
enum { SM_OK=0, SM_IO=-1, SM_PROTOCOL=-2, SM_BUSY=-3,
       SM_NO_DATA=-4, SM_RETRY=-5, SM_ARGUMENT=-6, SM_REJECTED=-7 };
enum { SM_CONFIG_WORDS=32, SM_RESULT_WORDS=32, SM_CLIP_WORDS=16 };
typedef struct { uint32_t protocol, firmware; uint64_t capabilities; } sm_identity;
typedef struct { uint32_t epoch, word[SM_RESULT_WORDS]; } sm_snapshot;
typedef struct { unsigned bank; uint32_t word[SM_CLIP_WORDS]; } sm_clip;

/* Configuration words: bytes for DDR addresses and lengths; word indices for
 * arena_words and descriptor indices. All DSP samples/FFT/outputs stay in PL. */
enum sm_config_index {
 SM_C_SESSION=0, SM_C_VERSION=1, SM_C_ARENA_BASE=2, SM_C_ARENA_WORDS=3,
 SM_C_RESERVED_LOW=4, SM_C_RESERVED_HIGH=5, SM_C_P1_DESCRIPTOR=6,
 SM_C_P2_DESCRIPTOR=7, SM_C_FLAGS=8, SM_C_BANK0=9, SM_C_BANK_BYTES=10,
 SM_C_RAW_LOW=11, SM_C_RAW_HIGH=12, SM_C_BANK1=13, SM_C_EVENT_ARM=14,
 SM_C_P1_LAST_INDEX=15, SM_C_EVENT_FIRST=16, SM_C_BAND_FIRST=22,
 SM_C_P1_STRIDE_WORDS=30, SM_C_P2_ONESHOT=31
};
enum { SM_P1_ENABLE=1, SM_P2_ENABLE=2, SM_PAUSE_P1=4, SM_RECORD_ENABLE=8 };
/* Faults bits0..19 are pipeline detail,20 recorder,21 lost-event,
 * 22 handoff-drop,23 sensor aggregate (detail in result28 bits23:16).
 * 30 config rejection,31 epoch overflow. No bit aliases sensor detail. */
enum sm_result_index {
 SM_R_PROTOCOL=0, SM_R_ALGORITHM=1, SM_R_FRAME=2, SM_R_CONFIG=3,
 SM_R_SESSION=4, SM_R_SLOT=5, SM_R_FFT_BASE=6, SM_R_CYCLES=7,
 SM_R_SAMPLE_LOW=8, SM_R_SAMPLE_HIGH=9, SM_R_FAULTS=10,
 SM_R_MIC_STATUS=11, SM_R_MISSED=12, SM_R_DROPPED=13,
 SM_R_BACKGROUND_DONE=14, SM_R_OVERWRITTEN=15, SM_R_FAILED=16,
 SM_R_TEMP_CENTI=17, SM_R_HUMIDITY=18, SM_R_PRESSURE_PA=19,
 SM_R_SOUND_SPEED_FLOAT=20, SM_R_SENSOR_VALID=21, SM_R_ROLL_PITCH=22,
 SM_R_YAW=23, SM_R_QW_QX=24, SM_R_QY_QZ=25, SM_R_ENV_SEQUENCE=26,
 SM_R_POSE_SEQUENCE=27, SM_R_SENSOR_ERRORS=28, SM_R_LOST_EVENTS=29,
 SM_R_HANDOFF_DROPS=30, SM_R_SAMPLE_RATE_FLOAT=31
};
enum sm_clip_index {
 SM_E_ID=0, SM_E_BASE=1, SM_E_OFFSET=2, SM_E_FRAMES=3,
 SM_E_FIRST_LOW=4, SM_E_FIRST_HIGH=5, SM_E_LAST_LOW=6, SM_E_LAST_HIGH=7,
 SM_E_INCOMPLETE=8, SM_E_SESSION=9, SM_E_CONFIG=10, SM_E_REASON=11,
 SM_E_PRE_Q22=12, SM_E_POST_Q22=13, SM_E_DELTA_Q22=14, SM_E_AGE_VALID=15
};
int sm_identify(const sm_device *, sm_identity *);
int sm_read_snapshot(const sm_device *, sm_snapshot *, unsigned attempts);
int sm_commit_config(const sm_device *, const uint32_t words[SM_CONFIG_WORDS]);
/* One poll, never busy-waits or blocks audio. Match expected config version. */
int sm_config_status(const sm_device *, uint32_t expected_version);
int sm_read_clip(const sm_device *, unsigned bank, sm_clip *);
/* Release only after BOTH ring segments are copied and cache maintenance done.
 * Wrong IDs are refused locally and by RTL. Released DDR is immediately reusable. */
int sm_release_clip(const sm_device *, const sm_clip *);
int sm_clear_irq(const sm_device *, uint32_t mask);
uint64_t sm_join_u64(uint32_t low, uint32_t high);
float sm_word_float(uint32_t word);
#ifdef __cplusplus
}
#endif
#endif
