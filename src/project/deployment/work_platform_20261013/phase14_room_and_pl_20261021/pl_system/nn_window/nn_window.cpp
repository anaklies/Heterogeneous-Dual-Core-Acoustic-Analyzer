#include "nn_window.h"
#include "../../../phase13_pl_port_20261021/nn/hls_parallel/variant4/srpdnn_v4.cpp"
#include "exp_lut.h"

static std::uint32_t exp_negative_q24(i32 x)
{
#pragma HLS INLINE off
    if(x<=-16384)return 0;
    if(x>=0)return 1u<<24;
    unsigned address=unsigned(x+16384),index=address>>2,remainder=address&3;
    std::uint64_t value=std::uint64_t(EXP_NEG_Q24[index])*(4-remainder)+
                        std::uint64_t(EXP_NEG_Q24[index+1])*remainder;
    return std::uint32_t((value+2)>>2);
}

extern "C" void nn_window(const i16 input[WINDOW_INPUT],i16 phase[WINDOW_PHASE],
    i16 support[WINDOW_SUPPORT],i16 logits[WINDOW_LOGITS],float vector[WINDOW_VECTOR],
    std::uint64_t metadata[WINDOW_META],std::uint64_t counters[WINDOW_COUNTERS])
{
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=features depth=153090 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=phase offset=slave bundle=network depth=51030 max_read_burst_length=64 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=support offset=slave bundle=network depth=25515 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=logits offset=slave bundle=network depth=31 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=vector offset=slave bundle=aggregate depth=1890 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=metadata offset=slave bundle=aggregate depth=5
#pragma HLS INTERFACE m_axi port=counters offset=slave bundle=aggregate depth=18
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=phase bundle=control
#pragma HLS INTERFACE s_axilite port=support bundle=control
#pragma HLS INTERFACE s_axilite port=logits bundle=control
#pragma HLS INTERFACE s_axilite port=vector bundle=control
#pragma HLS INTERFACE s_axilite port=metadata bundle=control
#pragma HLS INTERFACE s_axilite port=counters bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION function instances=pair_forward limit=1
    FixedStats stats_object={},aggregation_object={};
    FixedStats *stats=&stats_object;
    i16 pair_phase[FIX_PAIR_PHASE],pair_support[FIX_PAIR_SUPPORT],hidden[FIX_PAIR_HIDDEN];
    i32 sum_hidden[FIX_PAIR_HIDDEN]={};
    std::uint32_t sum_support[FIX_PAIR_SUPPORT]={};
    i16 global_hidden[FIX_PAIR_HIDDEN],maximum[48],activity[27],number[4];
    std::uint16_t weights[FIX_PAIR_SUPPORT];

    // One lexical paircore call. No templateinstantiation or UNROLL of15copies.
    for(int pair=0;pair<15;pair++) {
        pair_forward(input+pair*FIX_PAIR_INPUT,pair_phase,pair_support,hidden,stats);
        for(int i=0;i<FIX_PAIR_PHASE;i++) {
#pragma HLS PIPELINE II=1
            phase[pair*FIX_PAIR_PHASE+i]=pair_phase[i];
        }
        for(int i=0;i<FIX_PAIR_SUPPORT;i++) {
            support[pair*FIX_PAIR_SUPPORT+i]=pair_support[i];
            sum_support[i]+=unsigned(sigmoid(pair_support[i],&aggregation_object));
        }
        for(int i=0;i<FIX_PAIR_HIDDEN;i++) {
#pragma HLS PIPELINE II=1
            sum_hidden[i]+=hidden[i];
        }
    }
    for(int i=0;i<FIX_PAIR_HIDDEN;i++) {
#pragma HLS PIPELINE II=1
        i32 sum=sum_hidden[i];
        global_hidden[i]=sat(sum>=0?(sum+7)/15:-((-sum+7)/15),stats,SAT_GLOBAL_MEAN);
    }
    for(int c=0;c<48;c++) {
        maximum[c]=global_hidden[c];
        for(int t=1;t<27;t++)if(global_hidden[t*48+c]>maximum[c])maximum[c]=global_hidden[t*48+c];
    }
    for(int t=0;t<27;t++) {
        activity[t]=DENSE(global_hidden+t*48,W_ACTIVITY_WEIGHT,W_ACTIVITY_BIAS,0,48,14,SAT_ACTIVITY_AFFINE);
        logits[t]=activity[t];
    }
    for(int c=0;c<4;c++) {
        number[c]=DENSE(maximum,W_COUNT_WEIGHT,W_COUNT_BIAS,c,48,14,SAT_COUNT_AFFINE);
        logits[27+c]=number[c];
    }

    std::uint64_t mass=0,effective=0;
    for(int f=0;f<63;f++)for(int t=0;t<27;t++) {
        int k=f*27+t;
        // Supportmean is over15pairs. Gate >=0.5 BEFORE Q15weight rounding.
        std::uint64_t numerator=std::uint64_t(sum_support[k])*unsigned(sigmoid(activity[t],&aggregation_object));
        unsigned value=sum_support[k]>=15u*16384u?unsigned((numerator+245760u)/491520u):0;
        weights[k]=std::uint16_t(value);mass+=value;effective+=value!=0;
    }
    float normalization=mass?63.f/(8192.f*float(mass)):0.f;
    for(int p=0;p<15;p++)for(int component=0;component<2;component++)for(int f=0;f<63;f++) {
        i64 sum=0;
        for(int t=0;t<27;t++)sum+=i64(phase[((p*2+component)*63+f)*27+t])*weights[f*27+t];
        vector[(p*2+component)*63+f]=float(sum)*normalization;
    }
    i16 greatest=number[0];for(int c=1;c<4;c++)if(number[c]>greatest)greatest=number[c];
    std::uint32_t exponents[4];std::uint64_t denominator=0;
    for(int c=0;c<4;c++){exponents[c]=exp_negative_q24(i32(number[c])-greatest);denominator+=exponents[c];}
    std::uint64_t active_numerator=(denominator-exponents[0])*32768u;
    metadata[0]=mass;
    metadata[1]=(active_numerator+denominator/2)/denominator;
    metadata[2]=std::uint64_t(exponents[0])<=denominator-exponents[0];
    metadata[3]=effective;
    metadata[4]=aggregation_object.nonlinear_domain_clamp[1];
    for(int i=0;i<SAT_STAGE_COUNT;i++)counters[i]=stats->saturation[i];
    for(int i=0;i<3;i++)counters[SAT_STAGE_COUNT+i]=stats->nonlinear_domain_clamp[i];
}
