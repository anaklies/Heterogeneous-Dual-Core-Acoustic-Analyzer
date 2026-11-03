#ifndef GW_UTIL_H
#define GW_UTIL_H
/* Small portability/runtime helpers: monotonic clock, logging ring, bounded
 * message queue, byte FIFO, random tokens, decimal/hex parsing. */
#include <stddef.h>
#include <stdint.h>

#define GW_U32_MAX 4294967295u
#ifndef GW_U64_MAX
#define GW_U64_MAX 18446744073709551615ull
#endif

/* Monotonic clock in milliseconds / nanoseconds (never wall-clock). */
uint64_t gw_clock_ms(void);
uint64_t gw_clock_ns(void);
/* Deterministic test clock. When active, both clock functions derive from the
 * injected millisecond value (ns = ms * 1e6). Production never sets it. */
void gw_test_clock_set(uint64_t now_ms);
void gw_test_clock_reset(void);
int gw_test_clock_active(void);
void gw_sleep_ms(unsigned ms);
int gw_pid(void);

/* Cryptographic-quality entropy where the platform offers it, otherwise a
 * process-local PRNG mixed with ASLR/time/pid. Used for control tokens. */
void gw_random_bytes(void *out, size_t n);
void gw_hex_encode(const void *bytes, size_t n, char *out, size_t outcap);

/* Writes the decimal representation into out[21]; returns out. Portable
 * alternative to printf("%llu") on all host libcs. */
char *gw_u64_dec(uint64_t v, char out[21]);

int gw_parse_u64_dec(const char *s, size_t n, uint64_t *out);
int gw_parse_u32_dec(const char *s, size_t n, uint32_t *out);
/* Accepts optional 0x/0X prefix, 1..8 hex digits. */
int gw_parse_hex_u32(const char *s, size_t n, uint32_t *out);
int gw_parse_u32_hex_or_dec(const char *s, size_t n, uint32_t *out);

/* Fixed line ring for diagnostics.get. Oldest evicted with drop counter. */
#define GW_LOG_LINES 256
#define GW_LOG_LINE_BYTES 256
typedef struct {
    char line[GW_LOG_LINES][GW_LOG_LINE_BYTES];
    unsigned head;
    unsigned count;
    uint64_t dropped;
} gw_log;
void gw_log_init(gw_log *log);
void gw_log_add(gw_log *log, const char *fmt, ...);
unsigned gw_log_count(const gw_log *log);
const char *gw_log_at(const gw_log *log, unsigned idx); /* 0 = oldest */

/* Bounded queue of malloc'ed text lines (control notifications). Oldest line
 * is dropped when full and it is counted; data integrity lives on the binary
 * channel, so notification loss is permitted by PROTOCOL.md 2.4. */
#define GW_MSGQ_MAX 128
typedef struct {
    char *line[GW_MSGQ_MAX];
    unsigned head;
    unsigned count;
    uint64_t dropped;
} gw_msgq;
void gw_msgq_init(gw_msgq *q);
void gw_msgq_free(gw_msgq *q);
/* Returns 1 on success, 0 if allocation failed; drops oldest when full. */
int gw_msgq_push(gw_msgq *q, const char *line);
const char *gw_msgq_front(const gw_msgq *q);
void gw_msgq_pop(gw_msgq *q);
unsigned gw_msgq_count(const gw_msgq *q);

/* Byte FIFO with a hard capacity. push returns bytes actually written
 * (partial writes are possible; callers apply backpressure). */
typedef struct {
    uint8_t *buf;
    size_t cap;
    size_t head;
    size_t len;
    uint64_t dropped_bytes;
} gw_fifo;
int gw_fifo_init(gw_fifo *f, size_t cap);
void gw_fifo_free(gw_fifo *f);
size_t gw_fifo_write(gw_fifo *f, const void *data, size_t n);
size_t gw_fifo_read(gw_fifo *f, void *dst, size_t n);
size_t gw_fifo_avail(const gw_fifo *f);
/* Returns a pointer to the contiguous bytes at the head and their count. */
const uint8_t *gw_fifo_peek(const gw_fifo *f, size_t *contig);
void gw_fifo_consume(gw_fifo *f, size_t n);
size_t gw_fifo_space(const gw_fifo *f);
void gw_fifo_reset(gw_fifo *f);

/* Bit-stable float helpers (no host endian assumptions on the wire). */
float gw_word_to_float(uint32_t word);
uint32_t gw_float_to_word(float f);

/* Scratch string duplication (C99 has no strdup). */
char *gw_strdup(const char *s);
/* Creates path recursively (forward-slash separated). 0 = exists/created. */
int gw_mkdir_p(const char *path);
/* Bounded path helpers (avoid truncated snprintf paths on any compiler). */
int gw_path_join(const char *dir, const char *name, char *out, size_t cap);
int gw_str_concat(const char *prefix, const char *suffix, char *out, size_t cap);
char *gw_strndup(const char *s, size_t n);

#endif