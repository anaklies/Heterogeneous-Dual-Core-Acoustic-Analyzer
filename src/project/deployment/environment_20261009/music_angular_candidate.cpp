#include "nearfield_music.h"
#include <math.h>
#include "ieee_minmax.h"
#include <float.h>
#include <string.h>
#include "sine_table.h"
// Linear 1024-point periodic sine ROM; maximum interpolation error < 4.8e-6.
static float wave(float radians) {
#pragma HLS INLINE off
    float turn = radians * 0.15915494309189535f;
    int whole = (int)turn;
    if (turn < whole)
        whole--;
    float location = (turn - whole) * 1024;
    int index = (int)location;
    if (index > 1023)
        index = 1023;
    if (index < 0)
        index = 0;
    float fraction = location - index;
    return sine_table[index] + fraction * (sine_table[index + 1] - sine_table[index]);
}
static float sine(float angle) {
    return wave(angle);
}
static float cosine(float angle) {
    return wave(angle + 1.5707963267948966f);
}
struct C {
    float r, i;
};
static C cx(float r, float i = 0) {
    C a = {r, i};
    return a;
}
static C add(C a, C b) {
    return cx(a.r + b.r, a.i + b.i);
}
static C sub(C a, C b) {
    return cx(a.r - b.r, a.i - b.i);
}
static C mul(C a, C b) {
    return cx(a.r * b.r - a.i * b.i, a.r * b.i + a.i * b.r);
}
static C conjc(C a) {
    return cx(a.r, -a.i);
}
static C scale(C a, float s) {
    return cx(a.r * s, a.i * s);
}
static float power(C a) {
    return a.r * a.r + a.i * a.i;
}
static float clamp(float a, float lo, float hi) {
    return ieee_min(hi, ieee_max(lo, a));
}
static const float PI = 3.14159265358979323846f;
static void rotate2(C left, C right, C second, float cosine, float sine, C out[2]) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
    C z = mul(left, right);
    out[0] = sub(scale(z, cosine), scale(second, sine));
    out[1] = add(scale(z, sine), scale(second, cosine));
}
static void eig6(C a[6][6], C v[6][6], float d[6]) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION function instances = wave limit = 1
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fdiv limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
#pragma HLS ALLOCATION operation instances = flog limit = 1
#pragma HLS ALLOCATION operation instances = fsqrt limit = 1
    for (int i = 0; i < 6; i++)
        for (int j = 0; j < 6; j++)
            v[i][j] = cx(i == j ? 1 : 0);
    // Complex Hermitian Jacobi; bounded sweeps, no dynamic allocation.
    for (int sweep = 0; sweep < 32; sweep++)
        for (int p = 0; p < 5; p++)
            for (int q = p + 1; q < 6; q++) {
                float mag = sqrtf(power(a[p][q]));
                float trace = 0;
                for (int j = 0; j < 6; j++)
                    trace += fabsf(a[j][j].r);
                if (mag > ieee_max(trace * 1e-7f, 1e-14f)) {
                    C phase = scale(a[p][q], 1 / mag);
                    float tau = (a[q][q].r - a[p][p].r) / (2 * mag);
                    float t = (tau >= 0 ? 1.f : -1.f) / (fabsf(tau) + sqrtf(1 + tau * tau));
                    float c = 1 / sqrtf(1 + t * t), s = t * c;
                    C rotated[6][2];
                    for (int mode = 0; mode < 3; mode++) {
                        for (int k = 0; k < 6; k++) {
                            C first = mode == 0 ? a[k][p] : (mode == 1 ? a[p][k] : v[k][p]);
                            C second = mode == 0 ? a[k][q] : (mode == 1 ? a[q][k] : v[k][q]);
                            C left = mode == 1 ? conjc(phase) : first,
                              right = mode == 1 ? first : phase, result[2];
                            rotate2(left, right, second, c, s, result);
                            rotated[k][0] = result[0];
                            rotated[k][1] = result[1];
                        }
                        for (int k = 0; k < 6; k++) {
                            if (mode == 0) {
                                a[k][p] = rotated[k][0];
                                a[k][q] = rotated[k][1];
                            } else if (mode == 1) {
                                a[p][k] = rotated[k][0];
                                a[q][k] = rotated[k][1];
                            } else {
                                v[k][p] = rotated[k][0];
                                v[k][q] = rotated[k][1];
                            }
                        }
                    }
                    a[p][q] = cx(0);
                    a[q][p] = cx(0);
                    a[p][p].i = 0;
                    a[q][q].i = 0;
                }
            }
    for (int i = 0; i < 6; i++)
        d[i] = ieee_max(a[i][i].r, 1e-12f);
    for (int i = 0; i < 5; i++)
        for (int j = i + 1; j < 6; j++)
            if (d[j] > d[i]) {
                float tmp = d[i];
                d[i] = d[j];
                d[j] = tmp;
                for (int k = 0; k < 6; k++) {
                    C z = v[k][i];
                    v[k][i] = v[k][j];
                    v[k][j] = z;
                }
            }
}
static void multiply6(const C a[6][6], const C b[6][6], C c[6][6]) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION function instances = wave limit = 1
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fdiv limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
#pragma HLS ALLOCATION operation instances = flog limit = 1
#pragma HLS ALLOCATION operation instances = fsqrt limit = 1
    for (int i = 0; i < 6; i++)
        for (int j = 0; j < 6; j++) {
            C sum = cx(0);
            for (int k = 0; k < 6; k++)
                sum = add(sum, mul(a[i][k], b[k][j]));
            c[i][j] = sum;
        }
}
static void hermitian6(const C a[6][6], C b[6][6]) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION function instances = wave limit = 1
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fdiv limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
#pragma HLS ALLOCATION operation instances = flog limit = 1
#pragma HLS ALLOCATION operation instances = fsqrt limit = 1
    for (int i = 0; i < 6; i++)
        for (int j = 0; j < 6; j++)
            b[i][j] = conjc(a[j][i]);
}
static void direction(const float q[3], float u[3]) {
#pragma HLS INLINE
#pragma HLS ALLOCATION function instances = wave limit = 1
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fdiv limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
#pragma HLS ALLOCATION operation instances = flog limit = 1
#pragma HLS ALLOCATION operation instances = fsqrt limit = 1
    float az = q[0] * PI / 180, el = q[1] * PI / 180;
    u[0] = cosine(el) * cosine(az);
    u[1] = cosine(el) * sine(az);
    u[2] = sine(el);
}
#include "mic_geometry_coeff.h"
static C projectors[85][6][6], metrics[85][6][6];
static float weights[85];
static float scored_direction[3];
static float score_core(float azimuth, float elevation, float radius, float speed) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION function instances = wave limit = 1
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fdiv limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
#pragma HLS ALLOCATION operation instances = flog limit = 1
#pragma HLS ALLOCATION operation instances = fsqrt limit = 1
    float q[3] = {azimuth, elevation, radius};
    if (q[2] < .2f || q[2] > 8 || fabsf(q[1]) > 80)
        return 1e20f;
    float u[3], dist[6], amp[6];
    direction(q, u);
    for (int c = 0; c < 3; c++)
        scored_direction[c] = u[c];
    float norm = 0;
    for (int m = 0; m < 6; m++) {
        float z = 0;
        for (int c = 0; c < 3; c++) {
            float diff = q[2] * u[c] - MIC[m][c];
            z += diff * diff;
        }
        dist[m] = sqrtf(z);
        amp[m] = 1 / ieee_max(dist[m], .03f);
        norm += amp[m] * amp[m];
    }
    norm = sqrtf(norm);
    for (int m = 0; m < 6; m++)
        amp[m] /= norm;
    float value = 0;
    for (int f = 0; f < 85; f++)
        if (weights[f] > 0) {
            float hz = (5 + 4 * f) * 48000.f / 2048.f;
            C a[6];
            for (int m = 0; m < 6; m++) {
                float phase = -2 * PI * hz * (dist[m] - dist[0]) / speed;
                a[m] = cx(amp[m] * cosine(phase), amp[m] * sine(phase));
            }
            C n = cx(0), den = cx(0);
            for (int i = 0; i < 6; i++)
                for (int j = 0; j < 6; j++) {
                    C z = mul(conjc(a[i]), a[j]);
                    n = add(n, mul(z, projectors[f][i][j]));
                    den = add(den, mul(z, metrics[f][i][j]));
                }
            value += weights[f] * logf(ieee_max(n.r / ieee_max(den.r, 1e-12f), 1e-5f));
        }
    return value;
}
static bool search_one(int target, const float previous[3][3], float speed, float qbest[3],
                       bool &reliable) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION function instances = score_core limit = 1
#pragma HLS ALLOCATION function instances = direction limit = 1
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
#pragma HLS ALLOCATION operation instances = fdiv limit = 1
    const float ranges[9] = {.25f, .35f, .5f, .7f, 1, 1.5f, 2.5f, 4, 8},
                seeds[5] = {.35f, .7f, 1.5f, 2.3f, 3};
    float best = 1e20f, request[3] = {0, 0, 1}, value = 0, x[4][3], v[4], centroid[3], r[3],
          trial[3], vr = 0;
    float profile[180], profile_min = 1e20f;
    int state = 0, az = -180, el = -50, ri = 0, seed = 0, vertex = 0, iter = 0;
    bool outside = false;
    qbest[0] = 0;
    qbest[1] = 0;
    qbest[2] = 1;
    reliable = false;
    // All scoring requests use ONE call site, so HLS cannot clone the coarse,
    // simplex and range-profile scorers into independent circuits.
    // Worst-case bound: <30000 transitions, including 6*250 shrink iterations.
    for (int step = 0; step < 50000; step++) {
        bool evaluate = false;
        switch (state) {
        case 0: {
            request[0] = (float)az;
            request[1] = (float)el;
            request[2] = ranges[ri];
            evaluate = true;
            state = 1;
            break;
        }
        case 1: {
            bool separated = true;
            for (int old = 0; old < 3; old++)
                if (old < target) {
                    float dot = 0;
                    for (int c = 0; c < 3; c++)
                        dot += scored_direction[c] * previous[old][c];
                    if (dot > .9781476007f)
                        separated = false;
                }
            if (separated && value < best) {
                best = value;
                for (int c = 0; c < 3; c++)
                    qbest[c] = request[c];
            }
            state = 16;
            break;
        }
        case 16:
            ri++;
            if (ri == 9) {
                ri = 0;
                el += 10;
                if (el > 60) {
                    el = -50;
                    az += 10;
                }
            }
            if (az >= 180) {
                if (best >= 1e19f)
                    return false;
                state = 2;
            } else
                state = 0;
            break;
        case 2:
            for (int i = 0; i < 4; i++) {
                for (int c = 0; c < 3; c++)
                    x[i][c] = c == 2 ? (seed == 0 ? qbest[2] : seeds[seed - 1]) : qbest[c];
                if (i > 0)
                    x[i][i - 1] += i == 3 ? .08f : .5f;
            }
            vertex = 0;
            iter = 0;
            state = 3;
            break;
        case 3:
            for (int c = 0; c < 3; c++)
                request[c] = x[vertex][c];
            evaluate = true;
            state = 4;
            break;
        case 4:
            v[vertex] = value;
            vertex++;
            state = vertex < 4 ? 3 : 5;
            break;
        case 5: {
            if (iter >= 250) {
                state = 10;
                break;
            }
            for (int i = 0; i < 3; i++)
                for (int j = i + 1; j < 4; j++)
                    if (v[j] < v[i]) {
                        float tmp = v[i];
                        v[i] = v[j];
                        v[j] = tmp;
                        for (int c = 0; c < 3; c++) {
                            tmp = x[i][c];
                            x[i][c] = x[j][c];
                            x[j][c] = tmp;
                        }
                    }
            float spread = 0;
            for (int i = 1; i < 4; i++)
                for (int c = 0; c < 3; c++)
                    spread = ieee_max(spread, fabsf(x[i][c] - x[0][c]));
            if (spread < 1e-4f) {
                state = 10;
                break;
            }
            for (int c = 0; c < 3; c++) {
                centroid[c] = 0;
                for (int i = 0; i < 3; i++)
                    centroid[c] += x[i][c] / 3;
                r[c] = 2 * centroid[c] - x[3][c];
                request[c] = r[c];
            }
            evaluate = true;
            state = 6;
            break;
        }
        case 6:
            vr = value;
            if (vr < v[0]) {
                for (int c = 0; c < 3; c++) {
                    trial[c] = centroid[c] + 2 * (r[c] - centroid[c]);
                    request[c] = trial[c];
                }
                evaluate = true;
                state = 7;
            } else if (vr < v[2]) {
                for (int c = 0; c < 3; c++)
                    x[3][c] = r[c];
                v[3] = vr;
                iter++;
                state = 5;
            } else {
                outside = vr < v[3];
                for (int c = 0; c < 3; c++) {
                    trial[c] = centroid[c] + .5f * ((outside ? r[c] : x[3][c]) - centroid[c]);
                    request[c] = trial[c];
                }
                evaluate = true;
                state = 8;
            }
            break;
        case 7:
            for (int c = 0; c < 3; c++)
                x[3][c] = value < vr ? trial[c] : r[c];
            v[3] = ieee_min(value, vr);
            iter++;
            state = 5;
            break;
        case 8:
            if (value < (outside ? vr : v[3])) {
                for (int c = 0; c < 3; c++)
                    x[3][c] = trial[c];
                v[3] = value;
                iter++;
                state = 5;
            } else {
                vertex = 1;
                state = 9;
            }
            break;
        case 9:
            for (int c = 0; c < 3; c++) {
                x[vertex][c] = (x[vertex][c] + x[0][c]) / 2;
                request[c] = x[vertex][c];
            }
            evaluate = true;
            state = 11;
            break;
        case 11:
            v[vertex] = value;
            vertex++;
            if (vertex < 4)
                state = 9;
            else {
                iter++;
                state = 5;
            }
            break;
        case 10: {
            int bestvertex = 0;
            for (int i = 1; i < 4; i++)
                if (v[i] < v[bestvertex])
                    bestvertex = i;
            for (int c = 0; c < 3; c++)
                request[c] = x[bestvertex][c];
            evaluate = true;
            state = 12;
            break;
        }
        case 12:
            if (value < best) {
                best = value;
                for (int c = 0; c < 3; c++)
                    qbest[c] = request[c];
            }
            seed++;
            if (seed < 6)
                state = 2;
            else {
                ri = 0;
                state = 13;
            }
            break;
        case 13:
            request[0] = qbest[0];
            request[1] = qbest[1];
            request[2] = .2f + 7.8f * ri / 179;
            evaluate = true;
            state = 14;
            break;
        case 14:
            profile[ri] = value;
            profile_min = ieee_min(profile_min, value);
            ri++;
            state = ri < 180 ? 13 : 15;
            break;
        case 15: {
            float rlo = 9, rhi = 0;
            for (int i = 0; i < 180; i++)
                if (profile[i] <= profile_min + .01f) {
                    float radius = .2f + 7.8f * i / 179;
                    rlo = ieee_min(rlo, radius);
                    rhi = ieee_max(rhi, radius);
                }
            reliable = qbest[2] <= 3.2f && qbest[2] > .205f && rhi >= rlo && rhi - rlo < .30f;
            return true;
        }
        default:
            return false;
        }
        if (evaluate) {
            value = score_core(request[0], request[1], request[2], speed);
            if(state!=14 && value<1e19f) {
                for(int old=0;old<target;old++) {
                    float dot=0;
                    for(int c=0;c<3;c++)dot+=scored_direction[c]*previous[old][c];
                    if(dot>.9781476007f)value=1e20f;
                }
            }
        }
    }
    return false; // Bounded execution failure never creates a valid coordinate.
}
static int32_t fixed(float v) {
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
void nearfield_music(const int64_t cov_r[1785], const int64_t cov_i[1785], const int64_t bg_r[1785],
                     const int64_t bg_i[1785], const float mask[85], const float config[16],
                     int32_t output[52]) {
#pragma HLS INTERFACE ap_memory port = cov_r
#pragma HLS INTERFACE ap_memory port = cov_i
#pragma HLS INTERFACE ap_memory port = bg_r
#pragma HLS INTERFACE ap_memory port = bg_i
#pragma HLS INTERFACE ap_memory port = mask
#pragma HLS INTERFACE ap_memory port = config
#pragma HLS INTERFACE ap_memory port = output
#pragma HLS INTERFACE ap_ctrl_hs port = return
#pragma HLS ALLOCATION operation instances = fmul limit = 1
#pragma HLS ALLOCATION operation instances = fadd limit = 1
#pragma HLS ALLOCATION operation instances = fsub limit = 1
#pragma HLS ALLOCATION operation instances = fdiv limit = 1
#pragma HLS ALLOCATION operation instances = flog limit = 1
#pragma HLS ALLOCATION operation instances = fsqrt limit = 1
#pragma HLS ALLOCATION function instances = score_core limit = 1
#pragma HLS ALLOCATION function instances = direction limit = 1

#pragma HLS ALLOCATION function instances = eig6 limit = 1
#pragma HLS ALLOCATION function instances = multiply6 limit = 1
    // config: temperature, observations, background observations, enable background,
    //         rotation row-major 9 floats, dt, reset trackers, background energy ratio.

    int hist[4] = {0, 0, 0, 0};
    int usable = 0;
    float speed = 331.3f + .606f * clamp(config[0], -20, 60);
    int observations = (int)clamp(config[1], 2, 200);
    bool noisy = config[3] > .5f && config[15] >= .20f;
    for (int o = 0; o < 52; o++)
        output[o] = 0;
    for (int f = 0; f < 85; f++) {
        C a[6][6], b[6][6], wh[6][6], v[6][6];
        float d[6];
        int pair = 0;
        float trace = 0, off = 0;
        for (int i = 0; i < 6; i++)
            for (int j = i; j < 6; j++) {
                int index = f * 21 + pair++;
                a[i][j] =
                    cx((float)cov_r[index] / observations, (float)cov_i[index] / observations);
                a[j][i] = conjc(a[i][j]);
                b[i][j] = cx((float)bg_r[index] / ieee_max(config[2], 1),
                             (float)bg_i[index] / ieee_max(config[2], 1));
                b[j][i] = conjc(b[i][j]);
                if (i == j)
                    trace += b[i][j].r;
                else
                    off += 2 * power(b[i][j]);
            }
        for (int i = 0; i < 6; i++)
            for (int j = 0; j < 6; j++)
                wh[i][j] = cx(i == j ? 1 : 0);
        if (noisy) {
            float shrink = ieee_min(1, trace * trace / ieee_max(.5f * config[2] * off, 1e-20f));
            for (int i = 0; i < 6; i++)
                for (int j = 0; j < 6; j++)
                    if (i != j)
                        b[i][j] = scale(b[i][j], 1 - shrink);
            eig6(b, v, d);
            for (int i = 0; i < 6; i++)
                for (int j = 0; j < 6; j++) {
                    C z = cx(0);
                    for (int k = 0; k < 6; k++)
                        z = add(z, scale(mul(v[i][k], conjc(v[j][k])),
                                         1 / sqrtf(ieee_max(d[k], ieee_max(trace / 60, 1e-12f)))));
                    wh[i][j] = z;
                }
            C tmp[6][6], whh[6][6];
            multiply6(wh, a, tmp);
            hermitian6(wh, whh);
            multiply6(tmp, whh, a);
        }
        eig6(a, v, d);
        float mdlbest = 1e30f;
        int kbest = 0;
        for (int k = 0; k < 4; k++) {
            float logs = 0, mean = 0;
            for (int i = k; i < 6; i++) {
                logs += logf(d[i]);
                mean += d[i];
            }
            mean /= 6 - k;
            logs /= 6 - k;
            float mdl = -observations * (6 - k) * (logs - logf(ieee_max(mean, 1e-12f))) +
                        .5f * k * (12 - k) * logf((float)observations);
            if (mdl < mdlbest) {
                mdlbest = mdl;
                kbest = k;
            }
        }
        for (int repeat = 0; repeat < 3; repeat++)
            if (kbest > 0) {
                float tail = 0;
                for (int j = kbest; j < 6; j++)
                    tail += d[j];
                tail /= 6 - kbest;
                if (d[kbest - 1] < 3 * tail || d[kbest - 1] < .02f * d[0])
                    kbest--;
            }
        float tail = 0;
        int first = kbest > 1 ? kbest : 1;
        for (int j = first; j < 6; j++)
            tail += d[j];
        tail /= 6 - first;
        float strength = d[0] / ieee_max(tail, 1e-12f);
        weights[f] = 0;
        if (kbest > 0 && strength > 4) {
            weights[f] = ieee_min(10, strength) * (noisy ? (.3f + .7f * clamp(mask[f], 0, 1)) : 1);
            hist[kbest]++;
            usable++;
        }
        C noise[6][6], tmp[6][6], whh[6][6];
        for (int i = 0; i < 6; i++)
            for (int j = 0; j < 6; j++) {
                C z = cx(0);
                for (int k = kbest; k < 6; k++)
                    z = add(z, mul(v[i][k], conjc(v[j][k])));
                noise[i][j] = z;
            }
        hermitian6(wh, whh);
        multiply6(whh, noise, tmp);
        multiply6(tmp, wh, projectors[f]);
        multiply6(whh, wh, metrics[f]);
    }
    output[1] = usable;
    output[2] = noisy ? 1 : 0;
    if (usable < 8) {
        output[3] = 1;
        return;
    }
    int kth = (3 * usable + 3) / 4, K = 1, total = 0;
    for (int k = 1; k <= 3; k++) {
        total += hist[k];
        if (total >= kth) {
            K = k;
            break;
        }
    }
    float sumw = 0;
    for (int f = 0; f < 85; f++)
        sumw += weights[f];
    for (int f = 0; f < 85; f++)
        weights[f] /= ieee_max(sumw, 1e-12f);
    float estimates[3][3], directions[3][3],
        ranges[9] = {.25f, .35f, .5f, .7f, 1, 1.5f, 2.5f, 4, 8};
    bool reliable[3] = {false, false, false};
    int count = 0;
    for (int target = 0; target < 3; target++)
        if (target < K) {
            float qbest[3];
            bool accepted = false;
            if (search_one(target, directions, speed, qbest, accepted)) {
                for (int c = 0; c < 3; c++)
                    directions[target][c] = scored_direction[c];
                for (int c = 0; c < 3; c++)
                    estimates[target][c] = qbest[c];
                reliable[target] = accepted;
                count++;
            } else {
                output[3] = 2;
                break;
            }
        }
    output[0] = count;
    output[4] = fixed(speed);
    // Rotation in PL. Validate finite entries; invalid rotation falls back to local.
    bool rotation_ok = true;
    float normerr = 0;
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++) {
            float dot = 0;
            for (int k = 0; k < 3; k++)
                dot += config[4 + k * 3 + i] * config[4 + k * 3 + j];
            normerr += fabsf(dot - (i == j ? 1 : 0));
        }
    rotation_ok = isfinite(normerr) && normerr < .003f;
    for (int t = 0; t < 3; t++)
        if (t < count) {
            int base = 7 + t * 15;
            output[base] = t + 1;
            output[base + 1] = reliable[t] ? 1 : 0;
            float u[3] = {0, 0, 0};
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                    u[i] += (rotation_ok ? config[4 + i * 3 + j] : (i == j ? 1.f : 0.f)) *
                            directions[t][j];
            for (int c = 0; c < 3; c++) {
                output[base + 2 + c] = fixed(u[c]);
                output[base + 5 + c] = reliable[t] ? fixed(u[c] * estimates[t][2]) : 0;
            }
            output[base + 8] = fixed(estimates[t][2]);
            output[base + 9] = fixed(estimates[t][0]);
            output[base + 10] = fixed(estimates[t][1]);
        }
}

