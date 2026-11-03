#ifndef FC_CAPTURE_H
#define FC_CAPTURE_H
#include "gateway.h"
typedef struct fc_provenance {
 uint32_t session,config,frame;
 uint64_t first_sample,last_sample;
 float sample_rate;
 int gap;
 uint32_t frame_age_ms;
} fc_provenance;
typedef struct fc_raw_reader {
 int initialized,gap;
 uint32_t generation,base,bytes,session,config,rate,dropped;
 uint64_t next_record,next_sample;
} fc_raw_reader;
/* Zero initialize reader to begin at the next committed record. Sticky gap:
 * reset only when starting an explicitly new capture. CUR1 does not expose a
 * previous-bank final cursor: generation/bank changes cannot be bridged safely.
 * Same-generation ring wraps are supported. No DDR lease is acquired. */
int fc_raw_poll(gw *,fc_raw_reader *,uint32_t *,uint32_t,uint32_t *,fc_provenance *);
/* channel is zero based; data remains PL bit-preserving raw words. */
int fc_p0_read(gw *,const char *,unsigned,uint32_t *,uint32_t,uint32_t *,fc_provenance *);
/* Transport/display policy only: retain one actual PL frame, never synthesize
 * a spectrum or compute a per-bin peak spectrum on PS. */
void fc_transient_poll(gw *);
int fc_transient_read(gw *,const char *,unsigned,uint32_t *,uint32_t,uint32_t *,fc_provenance *);
#define FC_LIVE_WORDS (16u+3075u+48u+12288u)
/* New opt-in live stream: all values below are copied from one real PL frame. */
int fc_live_frame(gw*,unsigned,uint32_t,uint32_t,uint32_t*,fc_provenance*);
#endif
