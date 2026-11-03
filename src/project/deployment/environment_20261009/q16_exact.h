#ifndef SIXMIC_Q16_EXACT_H
#define SIXMIC_Q16_EXACT_H
#include <stdint.h>
#include <string.h>
static int32_t q16_exact(float v) {
#pragma HLS INLINE off
    // Exact IEEE-754 to Q16 conversion, including nonfinite rejection and
    // saturation. Bit extraction replaces floating clamps and multiplication.
    uint32_t raw;
    memcpy(&raw, &v, 4);
    uint32_t magnitude = raw & 0x7fffffff;
    if (magnitude >= 0x7f800000)
        return 0;
    uint32_t quantized = 0;
    if (magnitude > 0x46fffe00)
        quantized = 2147418112u;
    else {
        int exponent = (int)(magnitude >> 23), shift = exponent - 134;
        uint32_t mantissa = (magnitude & 0x7fffff) | 0x800000;
        if (exponent >= 111)
            quantized = shift >= 0 ? (mantissa << shift) : (mantissa >> (-shift));
    }
    return raw >> 31 ? -(int32_t)quantized : (int32_t)quantized;
}
#endif
