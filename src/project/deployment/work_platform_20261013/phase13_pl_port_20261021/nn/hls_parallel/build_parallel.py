"""Generate an isolated12-output first convolution, exact integer semantics."""
from pathlib import Path
import json,hashlib,subprocess,time
import numpy as np
P=Path(__file__).resolve().parent
F=P.parent/'fixed'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((P.parent/'tensor_manifest.json').read_text())
item=next(x for x in manifest['tensors'] if x['name']=='conv.weight')
allweights=np.fromfile(P.parent/'weights_i16.bin','<i2')
weights=allweights[item['offsetWords16']:item['offsetWords16']+item['elements']].reshape(12,90).T
header='// Exact original quantized weights, element-major12-output layout.\nstatic const i16 CONV_ELEMENTS[90][12]={\n'
header+=''.join('    {'+','.join(map(str,row.tolist()))+'},\n' for row in weights)+'};\n'
(P/'conv_elements.h').write_text(header)
source=(F/'srpdnn_fixed.cpp').read_text()
source=source.replace('#include "srpdnn_fixed.h"','#include "../fixed/srpdnn_fixed.h"')
source=source.replace('#include "weights_fixed.h"','#include "../fixed/weights_fixed.h"')
source=source.replace('#include "nonlinear_lut.h"','#include "../fixed/nonlinear_lut.h"')
start=source.index('    for (int oc=0;oc<12;++oc)',source.index('static void pair_forward'))
end=source.index('    for (int c=0;c<12;++c)',start)
source=source[:start]+'    convolution12(input,conv,stats);\n\n'+source[end:]
at=source.index('static void pair_forward')
kernel='''#include "conv_elements.h"
#ifdef __SYNTHESIS__
#include <ap_int.h>
using accum48=ap_int<48>;
#else
using accum48=i64;
#endif

// Only the first12-output convolution is transformed. Later layers stay exact.
// The worst90-product int16 dot plus bias is below2^38, so48bits is exact.
static void convolution12(const i16 external_input[FIX_PAIR_INPUT],i16 external_output[12*32*27],FixedStats *stats)
{
#pragma HLS INLINE off
#pragma HLS ARRAY_RESHAPE variable=CONV_ELEMENTS complete dim=2
#pragma HLS BIND_STORAGE variable=CONV_ELEMENTS type=rom_1p impl=bram
    i16 cached[FIX_PAIR_INPUT];
    i16 results[12*32*27];
#pragma HLS BIND_STORAGE variable=cached type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=results type=ram_s2p impl=bram
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
            for(int lane=0;lane<12;lane++) {
                results[(lane*32+f)*27+t]=gelu(affine_output(i64(accum[lane]),11+W_CONV_WEIGHT_FRAC,stats,SAT_CONV_AFFINE),stats);
            }
        }
    }
    for(int i=0;i<12*32*27;i++) {
#pragma HLS PIPELINE II=1
        external_output[i]=results[i];
    }
}

'''
source=source[:at]+kernel+source[at:]
source=source.replace('srpdnn_forward_fixed(', 'srpdnn_forward_parallel(')
(P/'srpdnn_parallel.cpp').write_text(source)
runner=(F/'run_fixed.cpp').read_text().replace('#include "srpdnn_fixed.h"','#include "../fixed/srpdnn_fixed.h"\nextern "C" void srpdnn_forward_parallel(const std::int16_t*,std::int16_t*,std::int16_t*,std::int16_t*,std::int16_t*,FixedStats*);').replace('srpdnn_forward_fixed(', 'srpdnn_forward_parallel(')
(P/'run_parallel.cpp').write_text(runner)
command=['D:/mingw64/bin/g++.exe','-O2','-std=c++17','-fno-fast-math',str(P/'srpdnn_parallel.cpp'),str(P/'run_parallel.cpp'),'-o',str(P/'parallel.exe')]
r=subprocess.run(command,capture_output=True,text=True);(P/'compile.log').write_text(r.stdout+r.stderr);r.check_returncode()
inp=F/'room0_speech_input_q11.bin';out=P/'speech_output_q.bin';stats=P/'speech_stats.txt'
begin=time.perf_counter();subprocess.run([str(P/'parallel.exe'),str(inp),str(out),str(stats)],check=True)
elapsed=time.perf_counter()-begin
gold=(F/'room0_speech_output_q.bin').read_bytes();observed=out.read_bytes()
assert gold==observed,'full network integer output mismatch'
goldstats=[int(v) for v in (F/'room0_speech_stats.txt').read_text().split()]
newstats=[int(v) for v in stats.read_text().split()]
assert goldstats==newstats,'counter mismatch'
result=dict(status='PASS',scope='full15pair C++ equivalence after changing only firstconvolution',
            comparedOutputInt16=len(gold)//2,allOutputBitExact=True,all18CountersExact=True,
            inputSHA256=sha(inp),goldenOutputSHA256=sha(F/'room0_speech_output_q.bin'),
            newOutputSHA256=sha(out),CPUSeconds=elapsed,fullNetwork10HzVerified=False,
            sources={str(p):sha(p) for p in [F/'srpdnn_fixed.cpp',P/'srpdnn_parallel.cpp',P/'conv_elements.h']})
(P/'C_EQUIVALENCE.json').write_text(json.dumps(result,indent=2))
print('PARALLEL_CONV12_C_EQUIVALENCE_PASS',len(gold)//2,'int16 plus18 counters')
