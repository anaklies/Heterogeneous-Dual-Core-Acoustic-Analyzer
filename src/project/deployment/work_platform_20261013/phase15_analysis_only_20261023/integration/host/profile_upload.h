#ifndef SIXMIC_PROFILE_UPLOAD_H
#define SIXMIC_PROFILE_UPLOAD_H
#include <stdint.h>
#include <stdio.h>
#include "sixmic_host.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef int (*sm_memory_write)(void*,uint32_t byte_address,const uint32_t*,uint32_t words);
typedef int (*sm_memory_clean)(void*,uint32_t byte_address,uint32_t bytes);
typedef struct {void*ctx;sm_memory_write write;sm_memory_clean clean;sm_barrier barrier;uint32_t arena_base,arena_words;} sm_upload_memory;
/* Preconditions: one owner; P1/P2 disabled by an actually-applied unique config,
 * all accepted work drained. This is NOT an AXI recovery/idle acknowledgement.
 * Validates the whole seekable SMI1 file before touching DDR. On any upload IO
 * failure keep services disabled; upload does not activate a configuration. */
int sm_upload_profile(FILE*,const sm_upload_memory*);
#ifdef __cplusplus
}
#endif
#endif
