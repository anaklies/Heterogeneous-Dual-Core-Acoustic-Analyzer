#include "utf8.h"

int gw_utf8_valid(const uint8_t *s, size_t n, size_t *bad_offset)
{
    size_t i = 0;
    while (i < n) {
        uint8_t b = s[i];
        size_t need;
        uint32_t cp;
        if (b < 0x80) { i++; continue; }
        if (b >= 0xC2 && b <= 0xDF) { need = 2; cp = (uint32_t)(b & 0x1F); }
        else if (b >= 0xE0 && b <= 0xEF) { need = 3; cp = (uint32_t)(b & 0x0F); }
        else if (b >= 0xF0 && b <= 0xF4) { need = 4; cp = (uint32_t)(b & 0x07); }
        else goto bad;
        if (i + need > n) goto bad;
        {
            size_t k;
            for (k = 1; k < need; k++) {
                uint8_t c = s[i + k];
                if ((c & 0xC0) != 0x80) goto bad;
                cp = (cp << 6) | (uint32_t)(c & 0x3F);
            }
        }
        if (need == 3 && cp < 0x800) goto bad;              /* overlong */
        if (need == 4 && cp < 0x10000) goto bad;            /* overlong */
        if (cp >= 0xD800 && cp <= 0xDFFF) goto bad;         /* surrogate */
        if (cp > 0x10FFFF) goto bad;                        /* out of range */
        i += need;
        continue;
bad:
        if (bad_offset) *bad_offset = i;
        return 0;
    }
    if (bad_offset) *bad_offset = 0;
    return 1;
}

size_t gw_utf8_decode(const uint8_t *s, size_t n, uint32_t *cp)
{
    uint8_t b;
    size_t need, k;
    uint32_t v;
    if (!s || n == 0) return 0;
    b = s[0];
    if (b < 0x80) { if (cp) *cp = b; return 1; }
    if (b >= 0xC2 && b <= 0xDF) { need = 2; v = (uint32_t)(b & 0x1F); }
    else if (b >= 0xE0 && b <= 0xEF) { need = 3; v = (uint32_t)(b & 0x0F); }
    else if (b >= 0xF0 && b <= 0xF4) { need = 4; v = (uint32_t)(b & 0x07); }
    else return 0;
    if (need > n) return 0;
    for (k = 1; k < need; k++) {
        uint8_t c = s[k];
        if ((c & 0xC0) != 0x80) return 0;
        v = (v << 6) | (uint32_t)(c & 0x3F);
    }
    if (need == 3 && v < 0x800) return 0;
    if (need == 4 && v < 0x10000) return 0;
    if (v >= 0xD800 && v <= 0xDFFF) return 0;
    if (v > 0x10FFFF) return 0;
    if (cp) *cp = v;
    return need;
}

size_t gw_utf8_encode(uint32_t cp, uint8_t out[4])
{
    if (!out) return 0;
    if (cp < 0x80) { out[0] = (uint8_t)cp; return 1; }
    if (cp < 0x800) {
        out[0] = (uint8_t)(0xC0 | (cp >> 6));
        out[1] = (uint8_t)(0x80 | (cp & 0x3F));
        return 2;
    }
    if (cp >= 0xD800 && cp <= 0xDFFF) return 0;
    if (cp < 0x10000) {
        out[0] = (uint8_t)(0xE0 | (cp >> 12));
        out[1] = (uint8_t)(0x80 | ((cp >> 6) & 0x3F));
        out[2] = (uint8_t)(0x80 | (cp & 0x3F));
        return 3;
    }
    if (cp <= 0x10FFFF) {
        out[0] = (uint8_t)(0xF0 | (cp >> 18));
        out[1] = (uint8_t)(0x80 | ((cp >> 12) & 0x3F));
        out[2] = (uint8_t)(0x80 | ((cp >> 6) & 0x3F));
        out[3] = (uint8_t)(0x80 | (cp & 0x3F));
        return 4;
    }
    return 0;
}
