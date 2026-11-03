#ifndef SIXMIC_RAW_CURSOR_H
#define SIXMIC_RAW_CURSOR_H
#include "sixmic_host.h"
#include "service_result.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {uint32_t word[16];} sm_raw_cursor;
typedef struct {sm_raw_cursor cursor;uint64_t first_sample,last_sample;uint32_t sequence_gaps;} sm_raw_copy;
/* Cursor is live telemetry, not a permanent DDR lease. A matching mapped
 * reserved-memory reader and cache invalidation callbacks are mandatory. */
int sm_read_raw_cursor(const sm_device*,sm_raw_cursor*,unsigned attempts);
/* record_index is an absolute RECORD number within generation, not sample ID.
 * The next-write slot is excluded even before its AXI B completion, to avoid
 * reading a partially overwritten oldest record. Captured sample IDs remain in each 32-byte record and preserve missing time.
 * Returns SM_NO_DATA if requested records expired/not yet produced and SM_RETRY
 * on bank change, overwrite while copying or nonmonotonic sample IDs. */
int sm_copy_raw_records(const sm_device*,const sm_memory*,uint64_t record_index,uint32_t frames,uint32_t *records,sm_raw_copy*);
#ifdef __cplusplus
}
#endif
#endif
