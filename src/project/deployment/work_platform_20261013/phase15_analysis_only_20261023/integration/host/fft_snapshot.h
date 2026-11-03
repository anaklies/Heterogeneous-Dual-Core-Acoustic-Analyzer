#ifndef SIXMIC_FFT_SNAPSHOT_H
#define SIXMIC_FFT_SNAPSHOT_H
#include "sixmic_host.h"
#include "service_result.h"
#ifdef __cplusplus
extern "C" {
#endif
/* One complete stream_fft2048 channel: 4096 complex words, 1025 triples
 * [amplitude,PSD,binPower], then 8 level/quality words. Selected channels are
 * packed in ascending order. m.reserved_low MUST be the active analysis arena
 * base, not merely a subrange. This is a generation check, not a lasting lease. */
int sm_copy_fft_snapshot(const sm_device*,const sm_memory*,const sm_snapshot *expected,uint32_t channels,uint32_t *data,uint32_t capacity_words);
#ifdef __cplusplus
}
#endif
#endif
