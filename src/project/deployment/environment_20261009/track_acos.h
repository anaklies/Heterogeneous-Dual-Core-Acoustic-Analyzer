#pragma once
#include <math.h>
// acos on [-1,1]: polynomial approximation of acos(abs(x))/sqrt(1-abs(x)).
// Only association cost uses this helper; localization never uses it.
static float track_acos(float x) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
    float a = fabsf(x);
    float p = -0.00122355611529f;
    p = p * a + 0.00651037879288f;
    p = p * a + -0.0168297700584f;
    p = p * a + 0.0306821614504f;
    p = p * a + -0.0500846877694f;
    p = p * a + 0.0889597833157f;
    p = p * a + -0.214597061276f;
    p = p * a + 1.5707962513f;
    float value = p * sqrtf(1.0f - a);
    return x < 0 ? 3.14159265358979323846f - value : value;
}
