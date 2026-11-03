#include "srpdnn_v4.cpp"
extern "C" void nn_parallel_v4(const i16 input[FIX_PAIR_INPUT],i16 output[6399],std::uint64_t counters[18])
{
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=audio depth=10206 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=results depth=6399 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=counters offset=slave bundle=results depth=18
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=output bundle=control
#pragma HLS INTERFACE s_axilite port=counters bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    FixedStats stats={};
    i16 phase[FIX_PAIR_PHASE],support[FIX_PAIR_SUPPORT],hidden[FIX_PAIR_HIDDEN];
    pair_forward(input,phase,support,hidden,&stats);
    for(int i=0;i<FIX_PAIR_PHASE;i++){
#pragma HLS PIPELINE II=1
        output[i]=phase[i];
    }
    for(int i=0;i<FIX_PAIR_SUPPORT;i++){
#pragma HLS PIPELINE II=1
        output[FIX_PAIR_PHASE+i]=support[i];
    }
    for(int i=0;i<FIX_PAIR_HIDDEN;i++){
#pragma HLS PIPELINE II=1
        output[FIX_PAIR_PHASE+FIX_PAIR_SUPPORT+i]=hidden[i];
    }
    for(int i=0;i<SAT_STAGE_COUNT;i++)counters[i]=stats.saturation[i];
    for(int i=0;i<3;i++)counters[SAT_STAGE_COUNT+i]=stats.nonlinear_domain_clamp[i];
}
