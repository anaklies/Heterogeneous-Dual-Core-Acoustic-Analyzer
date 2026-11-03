#include "C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase13_pl_port_20261021/nn/fixed/srpdnn_fixed.h"
#include "C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase13_pl_port_20261021/nn/fixed/weights_fixed.h"
#include "C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase13_pl_port_20261021/nn/fixed/nonlinear_lut.h"

using i16=std::int16_t;
using i32=std::int32_t;
using i64=std::int64_t;

// Signed rounding is nearest, ties away from zero. No right shift of a
// negative signed integer is used to define the rounding convention.
static i64 round_shift(i64 value, int shift)
{
    if (shift<=0) return value*(i64(1)<<(-shift));
    const i64 half=i64(1)<<(shift-1);
    return value>=0 ? (value+half)>>shift : -((-value+half)>>shift);
}

static i64 align(i64 value, int source_fraction, int target_fraction)
{
    return round_shift(value,source_fraction-target_fraction);
}

static i16 sat(i64 value, FixedStats *s, FixedStage stage)
{
    if (value>32767) { ++s->saturation[stage]; return 32767; }
    if (value<-32768) { ++s->saturation[stage]; return -32768; }
    return i16(value);
}

static i16 affine_output(i64 sum, int product_fraction, FixedStats *s, FixedStage stage)
{
    return sat(align(sum,product_fraction,10),s,stage);
}

static i16 dense(const i16 *input, const i16 *weight, const i16 *bias,
                 int row, int size, int input_fraction, int weight_fraction,
                 int bias_fraction, FixedStats *stats, FixedStage stage)
{
    const int product_fraction=input_fraction+weight_fraction;
    i64 sum=align(bias[row],bias_fraction,product_fraction);
    for (int i=0;i<size;++i)
        sum+=i64(weight[row*size+i])*input[i];
    return affine_output(sum,product_fraction,stats,stage);
}

// All three lookup tables have 4097 points over [-8,+8]. The Q10 input
// grid spacing is 4 integer units, and interpolation uses two fraction bits.
static i32 interpolate(const i32 *table, i32 x)
{
    const i32 address=x+8192;
    const int index=address>>2;
    const int remainder=address&3;
    if (index==4096) return table[index];
    return i32(round_shift(i64(table[index])*(4-remainder)+i64(table[index+1])*remainder,2));
}

static i16 gelu(i16 x, FixedStats *stats)
{
    if (x>8192) { ++stats->nonlinear_domain_clamp[0]; return x; }
    if (x<-8192) { ++stats->nonlinear_domain_clamp[0]; return 0; }
    return i16(interpolate(GELU_Q10,x));
}

static i32 sigmoid(i16 x, FixedStats *stats)
{
    if (x>8192) { ++stats->nonlinear_domain_clamp[1]; return 32768; }
    if (x<-8192) { ++stats->nonlinear_domain_clamp[1]; return 0; }
    return interpolate(SIGMOID_Q15,x);
}

static i16 tanh_q14(i16 x, FixedStats *stats)
{
    if (x>8192) { ++stats->nonlinear_domain_clamp[2]; return 16384; }
    if (x<-8192) { ++stats->nonlinear_domain_clamp[2]; return -16384; }
    return i16(interpolate(TANH_Q14,x));
}

#define DENSE(X,W,B,ROW,SIZE,INFRAC,STAGE) \
    dense(X,W,B,ROW,SIZE,INFRAC,W##_FRAC,B##_FRAC,stats,STAGE)


#ifdef __SYNTHESIS__
#include <ap_int.h>
using accum48=ap_int<48>;
#else
using accum48=i64;
#endif

// Pure finishing has no shared counter read-modify-write in the pipelined loop.
// Counter flags are summed locally and committed after the batch, exactly.
static i16 finish_scalar(i64 sum,int frac,int activation,unsigned &satflag,unsigned &clampflag)
{
#pragma HLS INLINE
    i64 scaled=align(sum,frac,10);
    satflag=scaled>32767||scaled<-32768;
    i16 x=scaled>32767?32767:(scaled<-32768?-32768:i16(scaled));
    clampflag=0;
    if(activation==0)return x;
    if(x>8192){clampflag=1;return activation==1?x:i16(16384);}
    if(x<-8192){clampflag=1;return activation==1?i16(0):i16(-16384);}
    return activation==1?i16(interpolate(GELU_Q10,x)):i16(interpolate(TANH_Q14,x));
}

#include "C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase13_pl_port_20261021/nn/hls_parallel/variant4/matrix_weights.h"
// All six dense/point kinds share this compute block. Each ROM is tensor-sized.
static void matrix12(const i16 vector[256],i16 result[144],int rows,int columns,int kind,
                     int input_fraction,FixedStats *stats,FixedStage stage,int activation)
{
#pragma HLS INLINE off
    int weight_fraction=0,bias_fraction=0;
    switch(kind){
        case 0:weight_fraction=W_POINT_WEIGHT_FRAC;bias_fraction=W_POINT_BIAS_FRAC;break;
        case 1:weight_fraction=W_EMBED_WEIGHT_FRAC;bias_fraction=W_EMBED_BIAS_FRAC;break;
        case 2:weight_fraction=W_GRU_WEIGHT_IH_L0_FRAC;bias_fraction=W_GRU_BIAS_IH_L0_FRAC;break;
        case 3:weight_fraction=W_GRU_WEIGHT_HH_L0_FRAC;bias_fraction=W_GRU_BIAS_HH_L0_FRAC;break;
        case 4:weight_fraction=W_PHASE_WEIGHT_FRAC;bias_fraction=W_PHASE_BIAS_FRAC;break;
        case 5:weight_fraction=W_SUPPORT_WEIGHT_FRAC;bias_fraction=W_SUPPORT_BIAS_FRAC;break;
    }
    const int frac=input_fraction+weight_fraction;
    for(int first=0;first<rows;first+=12){
#pragma HLS LOOP_TRIPCOUNT min=2 max=12
        accum48 accum[12];
#pragma HLS ARRAY_PARTITION variable=accum complete
        for(int lane=0;lane<12;lane++){
#pragma HLS UNROLL
            int row=first+lane;
            accum[lane]=0;
            // Input fraction is fixed by kind at the only matrix12 caller.
            // All bias conversions are exact left shifts, with no rounding.
            if(row<rows)switch(kind){
                case 0:accum[lane]=i64(W_POINT_BIAS[row])*(i64(1)<<(10+W_POINT_WEIGHT_FRAC-W_POINT_BIAS_FRAC));break;
                case 1:accum[lane]=i64(W_EMBED_BIAS[row])*(i64(1)<<(10+W_EMBED_WEIGHT_FRAC-W_EMBED_BIAS_FRAC));break;
                case 2:accum[lane]=i64(W_GRU_BIAS_IH_L0[row])*(i64(1)<<(10+W_GRU_WEIGHT_IH_L0_FRAC-W_GRU_BIAS_IH_L0_FRAC));break;
                case 3:accum[lane]=i64(W_GRU_BIAS_HH_L0[row])*(i64(1)<<(14+W_GRU_WEIGHT_HH_L0_FRAC-W_GRU_BIAS_HH_L0_FRAC));break;
                case 4:accum[lane]=i64(W_PHASE_BIAS[row])*(i64(1)<<(14+W_PHASE_WEIGHT_FRAC-W_PHASE_BIAS_FRAC));break;
                case 5:accum[lane]=i64(W_SUPPORT_BIAS[row])*(i64(1)<<(14+W_SUPPORT_WEIGHT_FRAC-W_SUPPORT_BIAS_FRAC));break;
            }
        }
        for(int column=0;column<columns;column++){
#pragma HLS LOOP_TRIPCOUNT min=12 max=256
#pragma HLS PIPELINE II=1
            int address=(first/12)*columns+column;i16 x=vector[column];
            std::uint64_t low=0,middle=0,high=0;
            switch(kind){
                case 0:low=T_POINT_0[address];middle=T_POINT_1[address];high=T_POINT_2[address];break;
                case 1:low=T_EMBED_0[address];middle=T_EMBED_1[address];high=T_EMBED_2[address];break;
                case 2:low=T_GI_0[address];middle=T_GI_1[address];high=T_GI_2[address];break;
                case 3:low=T_GH_0[address];middle=T_GH_1[address];high=T_GH_2[address];break;
                case 4:low=T_PHASE_0[address];middle=T_PHASE_1[address];high=T_PHASE_2[address];break;
                case 5:low=T_SUPPORT_0[address];middle=T_SUPPORT_1[address];high=T_SUPPORT_2[address];break;
            }
            for(int lane=0;lane<12;lane++){
#pragma HLS UNROLL
                std::uint64_t word=lane<4?low:(lane<8?middle:high);
                i16 w=i16((word>>(16*(lane%4)))&65535);
                accum[lane]+=i32(w)*i32(x);
            }
        }
        unsigned saturated=0,clamped=0;
        for(int lane=0;lane<12;lane++){
#pragma HLS PIPELINE II=1
            if(first+lane<rows){
                unsigned s,c;result[first+lane]=finish_scalar(i64(accum[lane]),frac,activation,s,c);
                saturated+=s;clamped+=c;
            }
        }
        stats->saturation[stage]+=saturated;
        if(activation)stats->nonlinear_domain_clamp[activation==1?0:2]+=clamped;
    }
}

static void depth12(const i16 conv[10368],i16 depth[5184],FixedStats *stats)
{
#pragma HLS INLINE off
    i16 bank[12][864];
#pragma HLS ARRAY_PARTITION variable=bank complete dim=1
#pragma HLS BIND_STORAGE variable=bank type=ram_s2p impl=bram
    for(int c=0;c<12;c++)for(int p=0;p<864;p++){
#pragma HLS PIPELINE II=1
        bank[c][p]=conv[c*864+p];
    }
    for(int f=0;f<16;f++)for(int t=0;t<27;t++){
        accum48 accum[12];
#pragma HLS ARRAY_PARTITION variable=accum complete
        for(int c=0;c<12;c++){
#pragma HLS UNROLL
            accum[c]=align(W_DEPTH_BIAS[c],W_DEPTH_BIAS_FRAC,10+W_DEPTH_WEIGHT_FRAC);
        }
        for(int element=0;element<9;element++){
#pragma HLS PIPELINE II=1
            int fi=2*f+element/3-1,ti=t+element%3-2;
            for(int c=0;c<12;c++){
#pragma HLS UNROLL
                i16 x=(fi>=0&&fi<32&&ti>=0&&ti<27)?bank[c][fi*27+ti]:i16(0);
                accum[c]+=i32(W_DEPTH_WEIGHT[c*9+element])*i32(x);
            }
        }
        unsigned saturated=0,clamped=0;
        for(int c=0;c<12;c++){
#pragma HLS PIPELINE II=1
            unsigned s,d;depth[(c*16+f)*27+t]=finish_scalar(i64(accum[c]),10+W_DEPTH_WEIGHT_FRAC,1,s,d);
            saturated+=s;clamped+=d;
        }
        stats->saturation[SAT_DEPTH_AFFINE]+=saturated;stats->nonlinear_domain_clamp[0]+=clamped;
    }
}

#include "C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase13_pl_port_20261021/nn/hls_parallel/conv_elements.h"
static void convolution12(const i16 external_input[FIX_PAIR_INPUT],i16 external_output[12*32*27],FixedStats *stats)
{
#pragma HLS INLINE off
#pragma HLS ARRAY_RESHAPE variable=CONV_ELEMENTS complete dim=2
#pragma HLS BIND_STORAGE variable=CONV_ELEMENTS type=rom_1p impl=bram
    i16 cached[FIX_PAIR_INPUT];
#pragma HLS BIND_STORAGE variable=cached type=ram_s2p impl=bram
    for(int i=0;i<FIX_PAIR_INPUT;i++) {
#pragma HLS PIPELINE II=1
        cached[i]=external_input[i];
    }
    for(int f=0;f<32;f++) {
        for(int t=0;t<27;t++) {
            accum48 accum[12];
#pragma HLS ARRAY_PARTITION variable=accum complete
            for(int lane=0;lane<12;lane++) {
#pragma HLS UNROLL
                accum[lane]=align(W_CONV_BIAS[lane],W_CONV_BIAS_FRAC,11+W_CONV_WEIGHT_FRAC);
            }
            for(int element=0;element<90;element++) {
#pragma HLS PIPELINE II=1
                int ic=element/15,kf=(element%15)/3,kt=element%3;
                int fi=2*f+kf-2,ti=t+kt-2;
                i16 x=(fi>=0&&fi<63&&ti>=0&&ti<27)?cached[(ic*63+fi)*27+ti]:i16(0);
                for(int lane=0;lane<12;lane++) {
#pragma HLS UNROLL
                    i32 product=i32(CONV_ELEMENTS[element][lane])*i32(x);
                    accum[lane]+=product;
                }
            }
            unsigned saturated=0,clamped=0;
            for(int lane=0;lane<12;lane++) {
#pragma HLS PIPELINE II=1
                unsigned s,c;
                external_output[(lane*32+f)*27+t]=finish_scalar(i64(accum[lane]),11+W_CONV_WEIGHT_FRAC,1,s,c);
                saturated+=s;clamped+=c;
            }
            stats->saturation[SAT_CONV_AFFINE]+=saturated;stats->nonlinear_domain_clamp[0]+=clamped;
        }
    }
}



// One lexicalcall to matrix12 forces the shared engine across all matrix jobs.
// Auto-outlined point/embed callers can no longer each clone the entire ROM set.
static void pair_forward(const i16 input[FIX_PAIR_INPUT],i16 phase[FIX_PAIR_PHASE],
                         i16 support[FIX_PAIR_SUPPORT],i16 hidden[FIX_PAIR_HIDDEN],FixedStats *stats)
{
#pragma HLS ALLOCATION function instances=matrix12 limit=1
    i16 conv[10368],depth[5184],point[6912],embedding[864];
    i16 h[48]={},next_h[48],input_gate[144],hidden_gate[144];
    i16 vector[256],result[144];
    convolution12(input,conv,stats);depth12(conv,depth,stats);
    for(int job=0;job<567;job++){
        int f=0,t=0,sub=0,rows=0,columns=0,kind=0,infrac=0,activation=0;
        FixedStage stage=SAT_POINT_AFFINE;
        if(job<432){
            f=job/27;t=job%27;rows=16;columns=12;kind=0;infrac=10;activation=1;stage=SAT_POINT_AFFINE;
            for(int c=0;c<12;c++){
#pragma HLS PIPELINE II=1
                vector[c]=depth[(c*16+f)*27+t];
            }
        }else if(job<459){
            t=job-432;rows=32;columns=256;kind=1;infrac=10;activation=1;stage=SAT_EMBED_AFFINE;
            for(int i=0;i<256;i++){
#pragma HLS PIPELINE II=1
                vector[i]=point[i*27+t];
            }
        }else{
            t=(job-459)/4;sub=(job-459)%4;
            if(sub==0){
                rows=144;columns=32;kind=2;infrac=10;activation=0;stage=SAT_GRU_INPUT_AFFINE;
                for(int i=0;i<32;i++){
#pragma HLS PIPELINE II=1
                    vector[i]=embedding[t*32+i];
                }
            }else{
                rows=sub==1?144:(sub==2?126:63);columns=48;kind=sub==1?3:(sub==2?4:5);
                infrac=14;activation=sub==2?2:0;
                stage=sub==1?SAT_GRU_HIDDEN_AFFINE:(sub==2?SAT_PHASE_AFFINE:SAT_SUPPORT_AFFINE);
                for(int i=0;i<48;i++){
#pragma HLS PIPELINE II=1
                    vector[i]=h[i];
                }
            }
        }
        matrix12(vector,result,rows,columns,kind,infrac,stats,stage,activation);
        if(job<432){
            for(int c=0;c<16;c++){
#pragma HLS PIPELINE II=1
                point[(c*16+f)*27+t]=result[c];
            }
        }else if(job<459){
            for(int c=0;c<32;c++){
#pragma HLS PIPELINE II=1
                embedding[t*32+c]=result[c];
            }
        }else if(sub==0){
            for(int g=0;g<144;g++){
#pragma HLS PIPELINE II=1
                input_gate[g]=result[g];
            }
        }else if(sub==1){
            for(int g=0;g<144;g++){
#pragma HLS PIPELINE II=1
                hidden_gate[g]=result[g];
            }
            for(int c=0;c<48;c++){
                const i16 reset_pre=sat(i32(input_gate[c])+hidden_gate[c],stats,SAT_GRU_RESET_PRE);
                const i16 update_pre=sat(i32(input_gate[48+c])+hidden_gate[48+c],stats,SAT_GRU_UPDATE_PRE);
                const i32 r=sigmoid(reset_pre,stats),z=sigmoid(update_pre,stats);
                const i16 new_pre=sat(i32(input_gate[96+c])+round_shift(i64(r)*hidden_gate[96+c],15),stats,SAT_GRU_NEW_PRE);
                const i16 n=tanh_q14(new_pre,stats);
                next_h[c]=sat(i32(n)+round_shift(i64(z)*(i32(h[c])-n),15),stats,SAT_GRU_HIDDEN);
            }
            for(int c=0;c<48;c++){
#pragma HLS PIPELINE II=1
                h[c]=next_h[c];hidden[t*48+c]=h[c];
            }
        }else if(sub==2){
            for(int c=0;c<126;c++){
#pragma HLS PIPELINE II=1
                phase[c*27+t]=result[c];
            }
        }else{
            for(int k=0;k<63;k++){
#pragma HLS PIPELINE II=1
                support[k*27+t]=result[k];
            }
        }
    }
}
extern "C" void srpdnn_forward_v4(const i16 input[FIX_PAIRS*FIX_PAIR_INPUT],
    i16 phase[FIX_PAIRS*FIX_PAIR_PHASE],i16 support[FIX_PAIRS*FIX_PAIR_SUPPORT],
    i16 activity[FIX_T],i16 count[4],FixedStats *stats)
{
    for (int i=0;i<SAT_STAGE_COUNT;++i) stats->saturation[i]=0;
    for (int i=0;i<3;++i) stats->nonlinear_domain_clamp[i]=0;
    i16 hidden[27*48],global_hidden[27*48];
    i32 sum_hidden[27*48]={};
    for (int p=0;p<15;++p) {
        pair_forward(input+p*FIX_PAIR_INPUT,phase+p*FIX_PAIR_PHASE,
                     support+p*FIX_PAIR_SUPPORT,hidden,stats);
        for (int i=0;i<27*48;++i) sum_hidden[i]+=hidden[i];
    }
    for (int i=0;i<27*48;++i) {
        const i32 s=sum_hidden[i];
        global_hidden[i]=sat(s>=0 ? (s+7)/15 : -((-s+7)/15),stats,SAT_GLOBAL_MEAN);
    }
    i16 maximum[48];
    for (int c=0;c<48;++c) {
        maximum[c]=global_hidden[c];
        for (int t=1;t<27;++t)
            if (global_hidden[t*48+c]>maximum[c]) maximum[c]=global_hidden[t*48+c];
    }
    for (int t=0;t<27;++t)
        activity[t]=DENSE(global_hidden+t*48,W_ACTIVITY_WEIGHT,W_ACTIVITY_BIAS,0,48,14,SAT_ACTIVITY_AFFINE);
    for (int c=0;c<4;++c)
        count[c]=DENSE(maximum,W_COUNT_WEIGHT,W_COUNT_BIAS,c,48,14,SAT_COUNT_AFFINE);
}
