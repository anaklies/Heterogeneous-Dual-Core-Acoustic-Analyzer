#ifndef GW_SPOOL_H
#define GW_SPOOL_H
/* Bounded on-disk event spool. One SMC1 container file per captured event.
 * The index is persisted as text so restart does not require directory
 * enumeration; acked event ids are tombstoned so event.ack stays idempotent.
 * No caller ever supplies a file path: names derive from the event id only. */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "sha256.h"
#include "gw_wire.h"

#define GW_SPOOL_MAX_EVENTS 256u
#define GW_SPOOL_PATH_BYTES 512u
#define GW_SPOOL_MAX_ACK_TOMBS 256u

typedef struct {
    uint64_t event_id;
    uint64_t total_bytes;
    uint64_t record_count;
    uint64_t first_sample;
    uint64_t last_sample;
    uint32_t flags;
    uint32_t clip_reason;
    uint32_t sample_rate_word;
    uint64_t created_ms;
    uint64_t created_unix_ms;
    char sha256[65];
    int acked;      /* file released after ack */
    int discarded;
    uint64_t protected_until_ms;
} gw_event_rec;

typedef struct {
    char root[GW_SPOOL_PATH_BYTES];
    char events_dir[GW_SPOOL_PATH_BYTES * 2];
    uint64_t limit_bytes;
    uint64_t used_bytes;
    uint64_t dropped_events;
    uint64_t dropped_bytes;
    uint64_t spool_io_errors;
    int circular;
    uint64_t evicted_events;
    gw_event_rec recs[GW_SPOOL_MAX_EVENTS];
    unsigned count;
    struct { uint64_t event_id; char sha256[65]; } tombs[GW_SPOOL_MAX_ACK_TOMBS];
    unsigned tomb_count;
    unsigned tomb_head;
} gw_spool;

typedef struct {
    gw_spool *spool; /* not owned; set by begin */
    FILE *f;
    char tmp_path[GW_SPOOL_PATH_BYTES * 2];
    char final_path[GW_SPOOL_PATH_BYTES * 2];
    gw_sha256_ctx hash;
    gw_smc1 hdr;
    uint64_t bytes;
    uint64_t need_bytes;
    int failed;
} gw_spool_writer;

/* Creates root/, root/events/ if absent. Loads index and acked tombstones. */
int gw_spool_init(gw_spool *s, const char *root, uint64_t limit_bytes,
                  char *err, size_t errcap);
void gw_spool_close(gw_spool *s);

const gw_event_rec *gw_spool_find(const gw_spool *s, uint64_t event_id);
const gw_event_rec *gw_spool_at(const gw_spool *s, unsigned idx);
unsigned gw_spool_count(const gw_spool *s);
/* Sorted ascending by event_id. Returns first index with id > cursor. */
unsigned gw_spool_index_after(const gw_spool *s, uint64_t cursor);
int gw_spool_is_acked(const gw_spool *s, uint64_t event_id, const char *sha256,
                      int *duplicate);

/* Streaming writer: writes the container header then appended raw records.
 * Capacity is checked before any file is created; if the spool cannot fit the
 * event it is dropped and counted (returns -3). */
int gw_spool_writer_begin(gw_spool *s, const gw_smc1 *hdr, gw_spool_writer *w,
                          char *err, size_t errcap);
int gw_spool_writer_write(gw_spool_writer *w, const void *data, size_t n);
int gw_spool_writer_finish(gw_spool *s, gw_spool_writer *w, gw_event_rec *out,
                           char *err, size_t errcap);
void gw_spool_writer_abort(gw_spool_writer *w);

/* Reads bytes [offset, offset+n) of the event container. Returns 0 ok. */
int gw_spool_read(const gw_spool *s, const gw_event_rec *rec, uint64_t offset,
                  void *dst, size_t n, char *err, size_t errcap);
/* Releases spool storage after verified ack. Duplicate ack of the same
 * eventId+sha256 is reported through *duplicate and returns 0. */
int gw_spool_ack(gw_spool *s, uint64_t event_id, const char *sha256,
                 int *duplicate, char *err, size_t errcap);
int gw_spool_discard(gw_spool *s, uint64_t event_id, char *err, size_t errcap);

#endif
