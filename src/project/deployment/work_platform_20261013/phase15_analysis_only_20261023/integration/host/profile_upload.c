#include "profile_upload.h"
#include <stdlib.h>
#include <string.h>

#define PRIVATE_WORD 524288u
#define MAX_IMAGE_BYTES (64u * 1024u * 1024u)

typedef struct { const unsigned char *data; size_t size, offset; } image_cursor;
static int word(image_cursor *r, uint32_t *value) {
    const unsigned char *p;
    if (r->offset > r->size || r->size - r->offset < 4) return -1;
    p = r->data + r->offset;
    *value = (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
             ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
    r->offset += 4;
    return 0;
}
static int scan(image_cursor r, uint32_t words) {
    uint32_t magic, size, start, count, off, n, last = PRIVATE_WORD;
    if (word(&r, &magic) || word(&r, &size) || word(&r, &start) || word(&r, &count)) return SM_PROTOCOL;
    if (magic != 0x31494d53u || size != words || start != PRIVATE_WORD || count != words - start) return SM_PROTOCOL;
    for (;;) {
        if (word(&r, &off) || word(&r, &n)) return SM_PROTOCOL;
        if (!n) return off == 0 && r.offset == r.size ? SM_OK : SM_PROTOCOL;
        if (off < last || off > words || n > words - off || (uint64_t)n * 4 > r.size - r.offset) return SM_PROTOCOL;
        r.offset += (size_t)n * 4;
        last = off + n;
    }
}
static int store(const sm_upload_memory *m, uint32_t off, const uint32_t *buffer, uint32_t n) {
    uint32_t address;
    /* Enforce the protected P0 boundary at the actual write, too. */
    if (off < PRIVATE_WORD || off > m->arena_words || n > m->arena_words - off) return SM_PROTOCOL;
    address = m->arena_base + 4 * off;
    if (m->write(m->ctx, address, buffer, n) || m->clean(m->ctx, address, 4 * n)) return SM_IO;
    return SM_OK;
}
int sm_upload_profile(FILE *file, const sm_upload_memory *m) {
    uint32_t buffer[256], off, n, i, left, at;
    long length;
    unsigned char *snapshot;
    image_cursor r;
    int result;
    if (!file || !m || !m->write || !m->clean || !m->barrier ||
        m->arena_words <= PRIVATE_WORD || m->arena_words > 4194304 || m->arena_base % 4096 ||
        (uint64_t)m->arena_base + 4ull * m->arena_words > 0x40000000ull) return SM_ARGUMENT;
    if (fseek(file, 0, SEEK_END) || (length = ftell(file)) < 24 ||
        (unsigned long)length > MAX_IMAGE_BYTES || fseek(file, 0, SEEK_SET)) return SM_PROTOCOL;
    snapshot = (unsigned char *)malloc((size_t)length);
    if (!snapshot) return SM_IO;
    if (fread(snapshot, 1, (size_t)length, file) != (size_t)length) { free(snapshot); return SM_IO; }
    r.data = snapshot; r.size = (size_t)length; r.offset = 0;
    /* Parse and upload the SAME bounded snapshot, never reread a mutable FILE. */
    result = scan(r, m->arena_words);
    if (result) { free(snapshot); return result; }
    memset(buffer, 0, sizeof buffer);
    for (at = PRIVATE_WORD; at < m->arena_words; at += n) {
        n = m->arena_words - at;
        if (n > 256) n = 256;
        result = store(m, at, buffer, n);
        if (result) { free(snapshot); return result; }
    }
    r.offset = 16;
    for (;;) {
        if (word(&r, &off) || word(&r, &left)) { result = SM_PROTOCOL; break; }
        if (!left) break;
        for (at = off; left; at += n, left -= n) {
            n = left > 256 ? 256 : left;
            for (i = 0; i < n; i++) {
                if (word(&r, &buffer[i])) { free(snapshot); return SM_PROTOCOL; }
            }
            result = store(m, at, buffer, n);
            if (result) { free(snapshot); return result; }
        }
    }
    if (!result) m->barrier(m->ctx);
    free(snapshot);
    return result;
}
