#include "sha256.h"
#include <stdio.h>
#include <string.h>

static const uint32_t K[64] = {
    0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,
    0x923f82a4u,0xab1c5ed5u,0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,
    0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,0xe49b69c1u,0xefbe4786u,
    0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
    0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,
    0x06ca6351u,0x14292967u,0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,
    0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,0xa2bfe8a1u,0xa81a664bu,
    0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
    0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,
    0x5b9cca4fu,0x682e6ff3u,0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,
    0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u};

static uint32_t ror(uint32_t x, unsigned n) { return (x >> n) | (x << (32 - n)); }

static void compress(gw_sha256_ctx *c, const uint8_t *p)
{
    uint32_t w[64], a, b, cc, d, e, f, g, h;
    unsigned i;
    for (i = 0; i < 16; i++) {
        w[i] = ((uint32_t)p[i*4] << 24) | ((uint32_t)p[i*4+1] << 16) |
               ((uint32_t)p[i*4+2] << 8) | (uint32_t)p[i*4+3];
    }
    for (i = 16; i < 64; i++) {
        uint32_t s0 = ror(w[i-15],7) ^ ror(w[i-15],18) ^ (w[i-15] >> 3);
        uint32_t s1 = ror(w[i-2],17) ^ ror(w[i-2],19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    a=c->h[0]; b=c->h[1]; cc=c->h[2]; d=c->h[3];
    e=c->h[4]; f=c->h[5]; g=c->h[6]; h=c->h[7];
    for (i = 0; i < 64; i++) {
        uint32_t S1 = ror(e,6) ^ ror(e,11) ^ ror(e,25);
        uint32_t ch = (e & f) ^ ((~e) & g);
        uint32_t t1 = h + S1 + ch + K[i] + w[i];
        uint32_t S0 = ror(a,2) ^ ror(a,13) ^ ror(a,22);
        uint32_t mj = (a & b) ^ (a & cc) ^ (b & cc);
        uint32_t t2 = S0 + mj;
        h=g; g=f; f=e; e=d+t1; d=cc; cc=b; b=a; a=t1+t2;
    }
    c->h[0]+=a; c->h[1]+=b; c->h[2]+=cc; c->h[3]+=d;
    c->h[4]+=e; c->h[5]+=f; c->h[6]+=g; c->h[7]+=h;
}

void gw_sha256_init(gw_sha256_ctx *c)
{
    static const uint32_t iv[8] = {0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
                                   0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u};
    memcpy(c->h, iv, sizeof iv);
    c->total = 0;
    c->block_len = 0;
}

void gw_sha256_update(gw_sha256_ctx *c, const void *data, size_t len)
{
    const uint8_t *p = (const uint8_t *)data;
    c->total += (uint64_t)len;
    while (len > 0) {
        size_t take = 64 - c->block_len;
        if (take > len) take = len;
        memcpy(c->block + c->block_len, p, take);
        c->block_len += take;
        p += take; len -= take;
        if (c->block_len == 64) { compress(c, c->block); c->block_len = 0; }
    }
}

void gw_sha256_final(gw_sha256_ctx *c, uint8_t out[32])
{
    uint64_t bits = c->total * 8u;
    unsigned i;
    c->block[c->block_len++] = 0x80;
    if (c->block_len > 56) {
        while (c->block_len < 64) c->block[c->block_len++] = 0;
        compress(c, c->block);
        c->block_len = 0;
    }
    while (c->block_len < 56) c->block[c->block_len++] = 0;
    for (i = 0; i < 8; i++) c->block[56 + i] = (uint8_t)(bits >> (56 - 8*i));
    compress(c, c->block);
    for (i = 0; i < 8; i++) {
        out[i*4]   = (uint8_t)(c->h[i] >> 24);
        out[i*4+1] = (uint8_t)(c->h[i] >> 16);
        out[i*4+2] = (uint8_t)(c->h[i] >> 8);
        out[i*4+3] = (uint8_t)c->h[i];
    }
}

void gw_sha256(const void *data, size_t len, uint8_t out[32])
{
    gw_sha256_ctx c;
    gw_sha256_init(&c);
    gw_sha256_update(&c, data, len);
    gw_sha256_final(&c, out);
}

void gw_sha256_hex(const uint8_t digest[32], char out[65])
{
    static const char hx[] = "0123456789abcdef";
    int i;
    for (i = 0; i < 32; i++) {
        out[i*2] = hx[digest[i] >> 4];
        out[i*2+1] = hx[digest[i] & 0x0F];
    }
    out[64] = 0;
}

void gw_sha256_file(const char *path, uint8_t out[32], uint64_t *size_out, int *io_error)
{
    FILE *f = fopen(path, "rb");
    gw_sha256_ctx c;
    uint8_t buf[8192];
    uint64_t total = 0;
    size_t n;
    if (io_error) *io_error = 0;
    memset(out, 0, 32);
    if (!f) { if (io_error) *io_error = 1; if (size_out) *size_out = 0; return; }
    gw_sha256_init(&c);
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) {
        gw_sha256_update(&c, buf, n);
        total += (uint64_t)n;
    }
    if (ferror(f)) { if (io_error) *io_error = 1; }
    fclose(f);
    gw_sha256_final(&c, out);
    if (size_out) *size_out = total;
}
