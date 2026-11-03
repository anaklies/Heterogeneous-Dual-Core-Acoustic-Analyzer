#if defined(_WIN32)
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#endif

#include "gw_util.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#endif

#if defined(_WIN32)
#include <direct.h>
#endif

/* ------------------------------------------------------------------- clock */

static int g_test_clock_active;
static uint64_t g_test_clock_ms;

void gw_test_clock_set(uint64_t now_ms)
{
    g_test_clock_ms = now_ms;
    g_test_clock_active = 1;
}

void gw_test_clock_reset(void)
{
    g_test_clock_active = 0;
    g_test_clock_ms = 0;
}

int gw_test_clock_active(void) { return g_test_clock_active; }

uint64_t gw_clock_ms(void)
{
    if (g_test_clock_active) return g_test_clock_ms;
#if defined(_WIN32)
    return (uint64_t)GetTickCount64();
#else
    {
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        return (uint64_t)ts.tv_sec * 1000u + (uint64_t)(ts.tv_nsec / 1000000);
    }
#endif
}

uint64_t gw_clock_ns(void)
{
    if (g_test_clock_active) return g_test_clock_ms * 1000000ull;
#if defined(_WIN32)
    {
        static LARGE_INTEGER freq;
        LARGE_INTEGER now;
        if (freq.QuadPart == 0) QueryPerformanceFrequency(&freq);
        QueryPerformanceCounter(&now);
        return (uint64_t)((double)now.QuadPart * 1e9 / (double)freq.QuadPart);
    }
#else
    {
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
    }
#endif
}

void gw_sleep_ms(unsigned ms)
{
#if defined(_WIN32)
    Sleep(ms);
#else
    struct timespec ts;
    ts.tv_sec = (time_t)(ms / 1000u);
    ts.tv_nsec = (long)(ms % 1000u) * 1000000L;
    nanosleep(&ts, NULL);
#endif
}

int gw_pid(void)
{
#if defined(_WIN32)
    return (int)GetCurrentProcessId();
#else
    return (int)getpid();
#endif
}

/* ----------------------------------------------------------------- entropy */

void gw_random_bytes(void *out, size_t n)
{
    uint8_t *p = (uint8_t *)out;
    size_t got = 0;
#if !defined(_WIN32)
    {
        FILE *f = fopen("/dev/urandom", "rb");
        if (f) {
            got = fread(p, 1, n, f);
            fclose(f);
        }
    }
#endif
    if (got < n) {
        static uint64_t state;
        uint64_t seed;
        size_t i;
        if (state == 0) {
            seed = gw_clock_ns() ^ ((uint64_t)(uintptr_t)&state << 17) ^
                   ((uint64_t)gw_pid() << 32) ^ (uint64_t)(uintptr_t)&got;
            state = seed ? seed : 0x9E3779B97F4A7C15ull;
        }
        for (i = got; i < n; i++) {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            p[i] = (uint8_t)(state >> 24);
        }
    }
}

void gw_hex_encode(const void *bytes, size_t n, char *out, size_t outcap)
{
    static const char hx[] = "0123456789abcdef";
    const uint8_t *p = (const uint8_t *)bytes;
    size_t i;
    if (outcap == 0) return;
    for (i = 0; i < n && (i * 2 + 2) <= outcap; i++) {
        out[i * 2] = hx[p[i] >> 4];
        out[i * 2 + 1] = hx[p[i] & 0x0F];
    }
    out[i * 2] = 0;
}

/* ----------------------------------------------------------------- parsing */

char *gw_u64_dec(uint64_t v, char out[21])
{
    char tmp[24];
    int n = 0;
    int i;
    if (v == 0) { out[0] = '0'; out[1] = 0; return out; }
    while (v > 0 && n < (int)sizeof tmp) {
        tmp[n++] = (char)('0' + (int)(v % 10u));
        v /= 10u;
    }
    for (i = 0; i < n; i++) out[i] = tmp[n - 1 - i];
    out[n] = 0;
    return out;
}

int gw_parse_u64_dec(const char *s, size_t n, uint64_t *out)
{
    uint64_t acc = 0;
    size_t i;
    if (!s || n == 0 || n > 20) return -1;
    for (i = 0; i < n; i++) {
        uint64_t d;
        if (s[i] < '0' || s[i] > '9') return -1;
        d = (uint64_t)(s[i] - '0');
        if (acc > (GW_U64_MAX - d) / 10u) return -1;
        acc = acc * 10u + d;
    }
    *out = acc;
    return 0;
}

int gw_parse_u32_dec(const char *s, size_t n, uint32_t *out)
{
    uint64_t v = 0;
    if (gw_parse_u64_dec(s, n, &v) != 0) return -1;
    if (v > GW_U32_MAX) return -1;
    *out = (uint32_t)v;
    return 0;
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int gw_parse_hex_u32(const char *s, size_t n, uint32_t *out)
{
    uint32_t v = 0;
    size_t i = 0;
    int digits = 0;
    if (!s) return -1;
    if (n >= 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) i = 2;
    if (i >= n) return -1;
    for (; i < n; i++) {
        int d = hexval(s[i]);
        if (d < 0) return -1;
        if (v > (GW_U32_MAX >> 4)) return -1;
        v = (v << 4) | (uint32_t)d;
        digits++;
        if (digits > 8) return -1;
    }
    *out = v;
    return 0;
}

int gw_parse_u32_hex_or_dec(const char *s, size_t n, uint32_t *out)
{
    if (!s || n == 0) return -1;
    if (n >= 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
        return gw_parse_hex_u32(s, n, out);
    return gw_parse_u32_dec(s, n, out);
}

/* --------------------------------------------------------------------- log */

void gw_log_init(gw_log *log)
{
    memset(log, 0, sizeof *log);
}

void gw_log_add(gw_log *log, const char *fmt, ...)
{
    char *dst;
    va_list ap;
    if (log->count == GW_LOG_LINES) {
        log->head = (log->head + 1) % GW_LOG_LINES;
        log->count--;
        log->dropped++;
    }
    dst = log->line[(log->head + log->count) % GW_LOG_LINES];
    va_start(ap, fmt);
    vsnprintf(dst, GW_LOG_LINE_BYTES, fmt, ap);
    va_end(ap);
    dst[GW_LOG_LINE_BYTES - 1] = 0;
    log->count++;
}

unsigned gw_log_count(const gw_log *log) { return log->count; }

const char *gw_log_at(const gw_log *log, unsigned idx)
{
    if (idx >= log->count) return "";
    return log->line[(log->head + idx) % GW_LOG_LINES];
}

/* -------------------------------------------------------------------- msgq */

void gw_msgq_init(gw_msgq *q) { memset(q, 0, sizeof *q); }

void gw_msgq_free(gw_msgq *q)
{
    while (q->count > 0) gw_msgq_pop(q);
}

int gw_msgq_push(gw_msgq *q, const char *line)
{
    char *copy = gw_strdup(line);
    if (!copy) return 0;
    if (q->count == GW_MSGQ_MAX) {
        free(q->line[q->head]);
        q->head = (q->head + 1u) % GW_MSGQ_MAX;
        q->count--;
        q->dropped++;
    }
    q->line[(q->head + q->count) % GW_MSGQ_MAX] = copy;
    q->count++;
    return 1;
}

const char *gw_msgq_front(const gw_msgq *q)
{
    return q->count ? q->line[q->head] : NULL;
}

void gw_msgq_pop(gw_msgq *q)
{
    if (q->count == 0) return;
    free(q->line[q->head]);
    q->line[q->head] = NULL;
    q->head = (q->head + 1u) % GW_MSGQ_MAX;
    q->count--;
}

unsigned gw_msgq_count(const gw_msgq *q) { return q->count; }

/* -------------------------------------------------------------------- fifo */

int gw_fifo_init(gw_fifo *f, size_t cap)
{
    memset(f, 0, sizeof *f);
    f->buf = (uint8_t *)malloc(cap ? cap : 1);
    if (!f->buf) return -1;
    f->cap = cap ? cap : 1;
    return 0;
}

void gw_fifo_free(gw_fifo *f)
{
    free(f->buf);
    memset(f, 0, sizeof *f);
}

size_t gw_fifo_write(gw_fifo *f, const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    size_t space = f->cap - f->len;
    size_t take = n < space ? n : space;
    size_t tail = (f->head + f->len) % f->cap;
    size_t first = f->cap - tail;
    if (take == 0) { f->dropped_bytes += n; return 0; }
    if (first > take) first = take;
    memcpy(f->buf + tail, p, first);
    if (take > first) memcpy(f->buf, p + first, take - first);
    f->len += take;
    if (take < n) f->dropped_bytes += (uint64_t)(n - take);
    return take;
}

size_t gw_fifo_read(gw_fifo *f, void *dst, size_t n)
{
    uint8_t *p = (uint8_t *)dst;
    size_t take = n < f->len ? n : f->len;
    size_t first = f->cap - f->head;
    if (first > take) first = take;
    memcpy(p, f->buf + f->head, first);
    if (take > first) memcpy(p + first, f->buf, take - first);
    f->head = (f->head + take) % f->cap;
    f->len -= take;
    return take;
}

size_t gw_fifo_avail(const gw_fifo *f) { return f->len; }

const uint8_t *gw_fifo_peek(const gw_fifo *f, size_t *contig)
{
    size_t first;
    if (f->len == 0) { if (contig) *contig = 0; return NULL; }
    first = f->cap - f->head;
    if (first > f->len) first = f->len;
    if (contig) *contig = first;
    return f->buf + f->head;
}

void gw_fifo_consume(gw_fifo *f, size_t n)
{
    if (n > f->len) n = f->len;
    f->head = (f->head + n) % f->cap;
    f->len -= n;
}
size_t gw_fifo_space(const gw_fifo *f) { return f->cap - f->len; }

void gw_fifo_reset(gw_fifo *f)
{
    f->head = 0;
    f->len = 0;
    f->dropped_bytes = 0;
}

/* ------------------------------------------------------------------ floats */

float gw_word_to_float(uint32_t word)
{
    float f;
    memcpy(&f, &word, sizeof f);
    return f;
}

uint32_t gw_float_to_word(float f)
{
    uint32_t w;
    memcpy(&w, &f, sizeof w);
    return w;
}

char *gw_strdup(const char *s)
{
    size_t n;
    char *p;
    if (!s) return NULL;
    n = strlen(s);
    p = (char *)malloc(n + 1);
    if (!p) return NULL;
    memcpy(p, s, n + 1);
    return p;
}

int gw_path_join(const char *dir, const char *name, char *out, size_t cap)
{
    size_t dn, nn;
    if (!dir || !name || !out || cap == 0) return -1;
    dn = strlen(dir);
    nn = strlen(name);
    if (dn + 1 + nn + 1 > cap) { out[0] = 0; return -1; }
    memcpy(out, dir, dn);
    out[dn] = '/';
    memcpy(out + dn + 1, name, nn + 1);
    return 0;
}

int gw_str_concat(const char *prefix, const char *suffix, char *out, size_t cap)
{
    size_t pn, sn;
    if (!prefix || !suffix || !out || cap == 0) return -1;
    pn = strlen(prefix);
    sn = strlen(suffix);
    if (pn + sn + 1 > cap) { out[0] = 0; return -1; }
    memcpy(out, prefix, pn);
    memcpy(out + pn, suffix, sn + 1);
    return 0;
}

int gw_mkdir_p(const char *path)
{
    char tmp[512];
    size_t n, i;
    if (!path || !*path) return -1;
    n = strlen(path);
    if (n >= sizeof tmp) return -1;
    memcpy(tmp, path, n + 1);
    for (i = 1; i < n; i++) {
        if (tmp[i] == '/' || tmp[i] == '\\') {
            tmp[i] = 0;
#if defined(_WIN32)
            _mkdir(tmp);
#else
            mkdir(tmp, 0755);
#endif
            tmp[i] = '/';
        }
    }
#if defined(_WIN32)
    if (_mkdir(tmp) == 0) return 0;
#else
    if (mkdir(tmp, 0755) == 0) return 0;
#endif
    return 0; /* EEXIST is success for our use */
}

char *gw_strndup(const char *s, size_t n)
{
    char *p = (char *)malloc(n + 1);
    if (!p) return NULL;
    memcpy(p, s, n);
    p[n] = 0;
    return p;
}