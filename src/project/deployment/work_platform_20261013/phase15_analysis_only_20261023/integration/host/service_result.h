#ifndef SIXMIC_SERVICE_RESULT_H
#define SIXMIC_SERVICE_RESULT_H
#include <stdint.h>
#include "sixmic_host.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef int (*sm_memory_read)(void *ctx,uint32_t byte_address,uint32_t *dst,uint32_t words);
typedef int (*sm_memory_invalidate)(void *ctx,uint32_t byte_address,uint32_t bytes);
typedef struct {void *ctx;sm_memory_read read;sm_memory_invalidate invalidate;sm_barrier barrier;uint32_t reserved_low,reserved_high;} sm_memory;
typedef struct {uint32_t word[16];} sm_service_result;
/* Read-side consistency only, NOT a permanent DDR lease. Retry if a service
 * restarts while copying. All callbacks operate on bit-preserving raw words. */
int sm_copy_service(const sm_memory *,uint32_t output_byte_address,uint32_t requested_words,uint32_t expected_session,uint32_t expected_config,uint32_t *data,sm_service_result *,unsigned attempts);
#ifdef __cplusplus
}
#endif
#endif
