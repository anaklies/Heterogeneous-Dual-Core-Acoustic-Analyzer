#ifndef GW_UTF8_H
#define GW_UTF8_H
/* Strict UTF-8 validation / codepoint decode-encode, C99, no locale. */
#include <stddef.h>
#include <stdint.h>

/* Returns 1 when s[0..n) is well-formed UTF-8 (no overlongs, no UTF-16
 * surrogates, max U+10FFFF, no truncated sequences). On failure returns 0 and
 * stores the byte offset of the first malformed byte in *bad_offset. */
int gw_utf8_valid(const uint8_t *s, size_t n, size_t *bad_offset);

/* Decodes one codepoint from s[0..n). Returns bytes consumed (1..4), 0 on
 * malformed input. */
size_t gw_utf8_decode(const uint8_t *s, size_t n, uint32_t *cp);

/* Encodes cp into out[0..3]. Returns byte count 1..4, 0 on invalid cp. */
size_t gw_utf8_encode(uint32_t cp, uint8_t out[4]);

#endif
