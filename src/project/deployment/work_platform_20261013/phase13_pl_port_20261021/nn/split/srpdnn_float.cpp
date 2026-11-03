#include "srpdnn_float.h"
#include "weights_float.h"
#include <cmath>

static float gelu(float x)
{
    return 0.5f * x * (1.0f + std::erf(x * 0.7071067811865475f));
}

static float sigmoid(float x)
{
    // This stable branch is algebraically equal to sigmoid. No LUT is used.
    if (x >= 0.0f) return 1.0f / (1.0f + std::exp(-x));
    const float e = std::exp(x);
    return e / (1.0f + e);
}

static float dense(const float *input, const float *weights,
                   const float *bias, int row, int input_size)
{
    float sum = bias[row];
    for (int c = 0; c < input_size; ++c)
        sum += weights[row * input_size + c] * input[c];
    return sum;
}

void srpdnn_pair_float(const float input[NN_PAIR_INPUT],
                      float phase[NN_PAIR_PHASE],
                      float support[NN_PAIR_SUPPORT],
                      float hidden[NN_PAIR_HIDDEN])
{
    // Local pair-at-a-time storage. No batch of 15 activation maps is required.
    float conv[12 * 32 * 27];
    float depth[12 * 16 * 27];
    float point[16 * 16 * 27];
    float embedding[27 * 32];
    float h[48] = {};
    float next_h[48];
    float in_gate[144], hidden_gate[144];

    // Conv2d padding=(2,2), stride=(2,1), followed by removal of two final frames.
    for (int oc = 0; oc < 12; ++oc)
        for (int f = 0; f < 32; ++f)
            for (int t = 0; t < 27; ++t) {
                float sum = W_CONV_BIAS[oc];
                for (int ic = 0; ic < 6; ++ic)
                    for (int kf = 0; kf < 5; ++kf)
                        for (int kt = 0; kt < 3; ++kt) {
                            const int fi = 2 * f + kf - 2;
                            const int ti = t + kt - 2;
                            if (fi >= 0 && fi < 63 && ti >= 0 && ti < 27) {
                                const int wi = ((oc * 6 + ic) * 5 + kf) * 3 + kt;
                                sum += W_CONV_WEIGHT[wi] * input[(ic * 63 + fi) * 27 + ti];
                            }
                        }
                conv[(oc * 32 + f) * 27 + t] = gelu(sum);
            }

    // Depthwise padding=(1,2), stride=(2,1), groups=12, same causal crop.
    for (int c = 0; c < 12; ++c)
        for (int f = 0; f < 16; ++f)
            for (int t = 0; t < 27; ++t) {
                float sum = W_DEPTH_BIAS[c];
                for (int kf = 0; kf < 3; ++kf)
                    for (int kt = 0; kt < 3; ++kt) {
                        const int fi = 2 * f + kf - 1;
                        const int ti = t + kt - 2;
                        if (fi >= 0 && fi < 32 && ti >= 0 && ti < 27)
                            sum += W_DEPTH_WEIGHT[(c * 3 + kf) * 3 + kt]
                                 * conv[(c * 32 + fi) * 27 + ti];
                    }
                depth[(c * 16 + f) * 27 + t] = gelu(sum);
            }

    for (int oc = 0; oc < 16; ++oc)
        for (int f = 0; f < 16; ++f)
            for (int t = 0; t < 27; ++t) {
                float sum = W_POINT_BIAS[oc];
                for (int ic = 0; ic < 12; ++ic)
                    sum += W_POINT_WEIGHT[oc * 12 + ic]
                         * depth[(ic * 16 + f) * 27 + t];
                point[(oc * 16 + f) * 27 + t] = gelu(sum);
            }

    for (int t = 0; t < 27; ++t)
        for (int oc = 0; oc < 32; ++oc) {
            float sum = W_EMBED_BIAS[oc];
            for (int i = 0; i < 256; ++i)
                sum += W_EMBED_WEIGHT[oc * 256 + i] * point[i * 27 + t];
            embedding[t * 32 + oc] = gelu(sum);
        }

    for (int t = 0; t < 27; ++t) {
        for (int gate = 0; gate < 144; ++gate) {
            in_gate[gate] = dense(embedding + t * 32,
                W_GRU_WEIGHT_IH_L0, W_GRU_BIAS_IH_L0, gate, 32);
            hidden_gate[gate] = dense(h,
                W_GRU_WEIGHT_HH_L0, W_GRU_BIAS_HH_L0, gate, 48);
        }
        for (int c = 0; c < 48; ++c) {
            // PyTorch gate row order is r,z,n. The reset gate multiplies the
            // hidden affine term INCLUDING b_hn (reset-after formulation).
            const float r = sigmoid(in_gate[c] + hidden_gate[c]);
            const float z = sigmoid(in_gate[48 + c] + hidden_gate[48 + c]);
            const float n = std::tanh(in_gate[96 + c] + r * hidden_gate[96 + c]);
            next_h[c] = n + z * (h[c] - n);
        }
        for (int c = 0; c < 48; ++c) {
            h[c] = next_h[c];
            hidden[t * 48 + c] = h[c];
        }
        for (int c = 0; c < 126; ++c) {
            const float y = dense(h, W_PHASE_WEIGHT,
                                  W_PHASE_BIAS, c, 48);
            phase[c * 27 + t] = 2.0f * std::tanh(y);
        }
        for (int f = 0; f < 63; ++f)
            support[f * 27 + t] = dense(h, W_SUPPORT_WEIGHT,
                                       W_SUPPORT_BIAS, f, 48);
    }
}

extern "C" void srpdnn_forward_float(
    const float input[NN_PAIRS * NN_PAIR_INPUT],
    float phase[NN_PAIRS * NN_PAIR_PHASE],
    float support[NN_PAIRS * NN_PAIR_SUPPORT],
    float activity[NN_TIMESTEPS], float count[4])
{
    float hidden[27 * 48];
    float global_hidden[27 * 48] = {};
    for (int pair = 0; pair < 15; ++pair) {
        srpdnn_pair_float(input + pair * NN_PAIR_INPUT,
                          phase + pair * NN_PAIR_PHASE,
                          support + pair * NN_PAIR_SUPPORT, hidden);
        for (int i = 0; i < 27 * 48; ++i)
            global_hidden[i] += hidden[i];
    }
    for (int i = 0; i < 27 * 48; ++i)
        global_hidden[i] /= 15.0f;
    float maximum[48];
    for (int c = 0; c < 48; ++c) {
        maximum[c] = global_hidden[c];
        for (int t = 1; t < 27; ++t)
            if (global_hidden[t * 48 + c] > maximum[c]) maximum[c] = global_hidden[t * 48 + c];
    }
    for (int t = 0; t < 27; ++t)
        activity[t] = dense(global_hidden + t * 48, W_ACTIVITY_WEIGHT,
                            W_ACTIVITY_BIAS, 0, 48);
    for (int c = 0; c < 4; ++c)
        count[c] = dense(maximum, W_COUNT_WEIGHT,
                         W_COUNT_BIAS, c, 48);
}
