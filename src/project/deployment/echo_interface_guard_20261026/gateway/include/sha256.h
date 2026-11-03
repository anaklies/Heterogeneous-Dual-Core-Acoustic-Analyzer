#ifndef GW_SHA256_H
#define GW_SHA256_H
/* Minimal FIPS 180-4 SHA-256 (C99, no external dependencies). */
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t h[8];
    uint64_t total;
    uint8_t block[64];
    size_t block_len;
} gw_sha256_ctx;

void gw_sha256_init(gw_sha256_ctx *ctx);
void gw_sha256_update(gw_sha256_ctx *ctx, const void *data, size_t len);
void gw_sha256_final(gw_sha256_ctx *ctx, uint8_t out[32]);
void gw_sha256(const void *data, size_t len, uint8_t out[32]);
void gw_sha256_hex(const uint8_t digest[32], char out[65]);
void gw_sha256_file(const char *path, uint8_t out[32], uint64_t *size_out, int *io_error);

#endif
