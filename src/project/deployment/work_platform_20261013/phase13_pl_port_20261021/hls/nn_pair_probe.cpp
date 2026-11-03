#include "../nn/srpdnn_float.cpp"

// Hardware resource/cycle probe of the mathematically validated float model.
// This is not the complete PCM front end or a deployed fixed-point network.
extern "C" void nn_pair_probe(const float input[NN_PAIR_INPUT], float output[NN_PAIR_PHASE+NN_PAIR_SUPPORT+NN_PAIR_HIDDEN])
{
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=audio depth=10206 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=results depth=6399 max_write_burst_length=64
#pragma HLS INTERFACE s_axilite port=return bundle=control
    srpdnn_pair_float(input, output, output+NN_PAIR_PHASE, output+NN_PAIR_PHASE+NN_PAIR_SUPPORT);
}
