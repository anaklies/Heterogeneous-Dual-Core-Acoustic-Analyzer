#include "../nn/split/srpdnn_float.cpp"
extern "C" void nn_split_probe(const float input[NN_PAIR_INPUT], float output[NN_PAIR_PHASE+NN_PAIR_SUPPORT+NN_PAIR_HIDDEN])
{
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=audio depth=10206 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=results depth=6399 max_write_burst_length=64
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=output bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    srpdnn_pair_float(input, output, output+NN_PAIR_PHASE, output+NN_PAIR_PHASE+NN_PAIR_SUPPORT);
}
