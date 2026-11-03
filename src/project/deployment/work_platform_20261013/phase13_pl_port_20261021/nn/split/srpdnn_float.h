#ifndef SIXMIC_SRPDNN_FLOAT_H
#define SIXMIC_SRPDNN_FLOAT_H

// Fixed shapes match the frozen J model. Inputs are pair_features, not PCM.
enum {
    NN_PAIRS = 15, NN_CHANNELS = 6, NN_FREQUENCIES = 63, NN_TIMESTEPS = 27,
    NN_PAIR_INPUT = 6 * 63 * 27,
    NN_PAIR_PHASE = 2 * 63 * 27,
    NN_PAIR_SUPPORT = 63 * 27,
    NN_PAIR_HIDDEN = 27 * 48
};

void srpdnn_pair_float(const float input[NN_PAIR_INPUT],
                      float phase[NN_PAIR_PHASE],
                      float support[NN_PAIR_SUPPORT],
                      float hidden[NN_PAIR_HIDDEN]);

extern "C" void srpdnn_forward_float(
    const float input[NN_PAIRS * NN_PAIR_INPUT],
    float phase[NN_PAIRS * NN_PAIR_PHASE],
    float support[NN_PAIRS * NN_PAIR_SUPPORT],
    float activity[NN_TIMESTEPS], float count[4]);

#endif
