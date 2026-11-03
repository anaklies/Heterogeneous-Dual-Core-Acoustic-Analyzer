"""One additional bounded candidate: shared12-output dense and depth kernels."""
from pathlib import Path
import json,hashlib,subprocess,time
import numpy as np
P=Path(__file__).resolve().parent
V=P/'variant2';V.mkdir(exist_ok=True)
F=P.parent/'fixed'
manifest=json.loads((P.parent/'tensor_manifest.json').read_text())
words=np.fromfile(P.parent/'weights_i16.bin','<i2')
def tensor(name):
    item=next(x for x in manifest['tensors'] if x['name']==name)
    return words[item['offsetWords16']:item['offsetWords16']+item['elements']].reshape(item['shape'])
defs=[('POINT','point.weight'),('EMBED','embed.weight'),('GI','gru.weight_ih_l0'),('GH','gru.weight_hh_l0'),('PHASE','phase.weight'),('SUPPORT','support.weight')]
header='// Exact original integer weights. Twelveoutput columns per ROM word.\n'
for short,name in defs:
    w=tensor(name).reshape(tensor(name).shape[0],-1);rows,cols=w.shape
    padded=np.zeros((((rows+11)//12)*12,cols),np.int16);padded[:rows]=w
    packed=padded.reshape(-1,12,cols).transpose(0,2,1).reshape(-1,12)
    header+=f'static const i16 T_{short}[{len(packed)}][12]={{\n'
    header+=''.join(' {'+','.join(map(str,row.tolist()))+'},\n' for row in packed)+'};\n'
(V/'matrix_weights.h').write_text(header)
helpers=(F/'srpdnn_fixed.cpp').read_text();helpers=helpers[:helpers.index('static void pair_forward')]
helpers=helpers.replace('#include "srpdnn_fixed.h"','#include "../../fixed/srpdnn_fixed.h"').replace('#include "weights_fixed.h"','#include "../../fixed/weights_fixed.h"').replace('#include "nonlinear_lut.h"','#include "../../fixed/nonlinear_lut.h"')
pure=r'''
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

#include "matrix_weights.h"
// All six dense/point kinds share this compute block. Each ROM is tensor-sized.
static void matrix12(const i16 vector[256],i16 result[144],int rows,int columns,int kind,
                     int input_fraction,FixedStats *stats,FixedStage stage,int activation)
{
#pragma HLS INLINE off
#pragma HLS ARRAY_RESHAPE variable=T_POINT complete dim=2
#pragma HLS ARRAY_RESHAPE variable=T_EMBED complete dim=2
#pragma HLS ARRAY_RESHAPE variable=T_GI complete dim=2
#pragma HLS ARRAY_RESHAPE variable=T_GH complete dim=2
#pragma HLS ARRAY_RESHAPE variable=T_PHASE complete dim=2
#pragma HLS ARRAY_RESHAPE variable=T_SUPPORT complete dim=2
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
            int row=first+lane;i16 bias=0;
            if(row<rows)switch(kind){
                case 0:bias=W_POINT_BIAS[row];break;case 1:bias=W_EMBED_BIAS[row];break;
                case 2:bias=W_GRU_BIAS_IH_L0[row];break;case 3:bias=W_GRU_BIAS_HH_L0[row];break;
                case 4:bias=W_PHASE_BIAS[row];break;case 5:bias=W_SUPPORT_BIAS[row];break;
            }
            accum[lane]=align(bias,bias_fraction,frac);
        }
        for(int column=0;column<columns;column++){
#pragma HLS LOOP_TRIPCOUNT min=12 max=256
#pragma HLS PIPELINE II=1
            int address=(first/12)*columns+column;i16 x=vector[column];
            for(int lane=0;lane<12;lane++){
#pragma HLS UNROLL
                i16 w=0;
                switch(kind){
                    case 0:w=T_POINT[address][lane];break;case 1:w=T_EMBED[address][lane];break;
                    case 2:w=T_GI[address][lane];break;case 3:w=T_GH[address][lane];break;
                    case 4:w=T_PHASE[address][lane];break;case 5:w=T_SUPPORT[address][lane];break;
                }
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
'''
conv=(P/'srpdnn_parallel.cpp').read_text();conv=conv[conv.index('static void convolution12'):conv.index('static void pair_forward')]
old='''            for(int lane=0;lane<12;lane++) {
                results[(lane*32+f)*27+t]=gelu(affine_output(i64(accum[lane]),11+W_CONV_WEIGHT_FRAC,stats,SAT_CONV_AFFINE),stats);
            }'''
new='''            unsigned saturated=0,clamped=0;
            for(int lane=0;lane<12;lane++) {
#pragma HLS PIPELINE II=1
                unsigned s,c;
                results[(lane*32+f)*27+t]=finish_scalar(i64(accum[lane]),11+W_CONV_WEIGHT_FRAC,1,s,c);
                saturated+=s;clamped+=c;
            }
            stats->saturation[SAT_CONV_AFFINE]+=saturated;stats->nonlinear_domain_clamp[0]+=clamped;'''
assert old in conv;conv=conv.replace(old,new)
pair=r'''
static void pair_forward(const i16 input[FIX_PAIR_INPUT],i16 phase[FIX_PAIR_PHASE],
                         i16 support[FIX_PAIR_SUPPORT],i16 hidden[FIX_PAIR_HIDDEN],FixedStats *stats)
{
#pragma HLS ALLOCATION function instances=matrix12 limit=1
    i16 conv[10368],depth[5184],point[6912],embedding[864];
    i16 h[48]={},next_h[48],input_gate[144],hidden_gate[144];
    i16 vector[256],result[144];
    convolution12(input,conv,stats);depth12(conv,depth,stats);
    for(int f=0;f<16;f++)for(int t=0;t<27;t++){
        for(int c=0;c<12;c++)vector[c]=depth[(c*16+f)*27+t];
        matrix12(vector,result,16,12,0,10,stats,SAT_POINT_AFFINE,1);
        for(int c=0;c<16;c++)point[(c*16+f)*27+t]=result[c];
    }
    for(int t=0;t<27;t++){
        for(int i=0;i<256;i++)vector[i]=point[i*27+t];
        matrix12(vector,result,32,256,1,10,stats,SAT_EMBED_AFFINE,1);
        for(int c=0;c<32;c++)embedding[t*32+c]=result[c];
    }
    for(int t=0;t<27;t++){
        for(int i=0;i<32;i++)vector[i]=embedding[t*32+i];
        matrix12(vector,result,144,32,2,10,stats,SAT_GRU_INPUT_AFFINE,0);
        for(int g=0;g<144;g++)input_gate[g]=result[g];
        for(int i=0;i<48;i++)vector[i]=h[i];
        matrix12(vector,result,144,48,3,14,stats,SAT_GRU_HIDDEN_AFFINE,0);
        for(int g=0;g<144;g++)hidden_gate[g]=result[g];
        for(int c=0;c<48;c++){
            const i16 reset_pre=sat(i32(input_gate[c])+hidden_gate[c],stats,SAT_GRU_RESET_PRE);
            const i16 update_pre=sat(i32(input_gate[48+c])+hidden_gate[48+c],stats,SAT_GRU_UPDATE_PRE);
            const i32 r=sigmoid(reset_pre,stats),z=sigmoid(update_pre,stats);
            const i16 new_pre=sat(i32(input_gate[96+c])+round_shift(i64(r)*hidden_gate[96+c],15),stats,SAT_GRU_NEW_PRE);
            const i16 n=tanh_q14(new_pre,stats);
            next_h[c]=sat(i32(n)+round_shift(i64(z)*(i32(h[c])-n),15),stats,SAT_GRU_HIDDEN);
        }
        for(int c=0;c<48;c++){h[c]=next_h[c];hidden[t*48+c]=h[c];vector[c]=h[c];}
        matrix12(vector,result,126,48,4,14,stats,SAT_PHASE_AFFINE,2);
        for(int c=0;c<126;c++)phase[c*27+t]=result[c];
        matrix12(vector,result,63,48,5,14,stats,SAT_SUPPORT_AFFINE,0);
        for(int f=0;f<63;f++)support[f*27+t]=result[f];
    }
}
'''
full=(F/'srpdnn_fixed.cpp').read_text();full=full[full.index('extern "C" void srpdnn_forward_fixed'):].replace('srpdnn_forward_fixed(', 'srpdnn_forward_v2(')
source=helpers+pure+'\n#include "../conv_elements.h"\n'+conv+pair+full
(V/'srpdnn_v2.cpp').write_text(source)
runner=(F/'run_fixed.cpp').read_text().replace('#include "srpdnn_fixed.h"','#include "../../fixed/srpdnn_fixed.h"\nextern "C" void srpdnn_forward_v2(const std::int16_t*,std::int16_t*,std::int16_t*,std::int16_t*,std::int16_t*,FixedStats*);').replace('srpdnn_forward_fixed(', 'srpdnn_forward_v2(')
(V/'run_v2.cpp').write_text(runner)
r=subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-std=c++17','-fno-fast-math',str(V/'srpdnn_v2.cpp'),str(V/'run_v2.cpp'),'-o',str(V/'v2.exe')],capture_output=True,text=True)
(V/'compile.log').write_text(r.stdout+r.stderr);r.check_returncode()
rows=[]
for kind in ['speech','broad']:
    inp=F/f'room0_{kind}_input_q11.bin';out=V/f'{kind}_output_q.bin';stats=V/f'{kind}_stats.txt'
    start=time.perf_counter();subprocess.run([str(V/'v2.exe'),str(inp),str(out),str(stats)],check=True)
    assert out.read_bytes()==(F/f'room0_{kind}_output_q.bin').read_bytes(),kind
    assert stats.read_text().split()==(F/f'room0_{kind}_stats.txt').read_text().split(),kind
    rows.append(dict(kind=kind,comparedOutputInt16=len(out.read_bytes())//2,allOutputBitExact=True,all18CountersExact=True,CPUSeconds=time.perf_counter()-start))
(V/'C_EQUIVALENCE.json').write_text(json.dumps(dict(status='PASS',rows=rows,fullNetwork10HzVerified=False),indent=2))
print('VARIANT2_C_BITEXACT_PASS',len(rows),'full15pair cases')
