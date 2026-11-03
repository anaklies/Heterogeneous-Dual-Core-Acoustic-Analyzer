"""Repair observed ROM replication and outlining; no arithmetic change."""
from pathlib import Path
import json,hashlib,subprocess,time,re
import numpy as np
P=Path(__file__).resolve().parent;V=P/'variant3';V.mkdir(exist_ok=True);F=P.parent/'fixed'
manifest=json.loads((P.parent/'tensor_manifest.json').read_text());words=np.fromfile(P.parent/'weights_i16.bin','<i2')
defs=[('POINT','point.weight'),('EMBED','embed.weight'),('GI','gru.weight_ih_l0'),('GH','gru.weight_hh_l0'),('PHASE','phase.weight'),('SUPPORT','support.weight')]
header='// Three explicit64-bit loads precede laneunrolling. No12-port ROM replication.\n'
for short,name in defs:
    item=next(x for x in manifest['tensors'] if x['name']==name)
    w=words[item['offsetWords16']:item['offsetWords16']+item['elements']].reshape(item['shape'][0],-1);rows,cols=w.shape
    padded=np.zeros((((rows+11)//12)*12,cols),np.int16);padded[:rows]=w
    packed=padded.reshape(-1,12,cols).transpose(0,2,1).reshape(-1,12)
    for group in range(3):
        data=[sum((int(row[4*group+i])&65535)<<(16*i) for i in range(4)) for row in packed]
        header+=f'static const std::uint64_t T_{short}_{group}[{len(data)}]={{\n'
        header+=''.join(f' 0x{x:016x}ULL,\n' for x in data)+'};\n'
(V/'matrix_weights.h').write_text(header)
source=(P/'variant2/srpdnn_v2.cpp').read_text()
source=re.sub(r'^#pragma HLS ARRAY_RESHAPE variable=T_.*\n','',source,flags=re.M)
start=source.index('            int address=(first/12)*columns+column;i16 x=vector[column];')
end=source.index('        unsigned saturated=0,clamped=0;',start)
replacement='''            int address=(first/12)*columns+column;i16 x=vector[column];
            std::uint64_t low=0,middle=0,high=0;
            switch(kind){
'''
for kind,(short,_) in enumerate(defs):
    replacement+=f'                case {kind}:low=T_{short}_0[address];middle=T_{short}_1[address];high=T_{short}_2[address];break;\n'
replacement+='''            }
            for(int lane=0;lane<12;lane++){
#pragma HLS UNROLL
                std::uint64_t word=lane<4?low:(lane<8?middle:high);
                i16 w=i16((word>>(16*(lane%4)))&65535);
                accum[lane]+=i32(w)*i32(x);
            }
        }
'''
source=source[:start]+replacement+source[end:]
start=source.index('static void pair_forward(')
end=source.index('extern "C" void srpdnn_forward_v2',start)
pair=r'''
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
            for(int c=0;c<12;c++)vector[c]=depth[(c*16+f)*27+t];
        }else if(job<459){
            t=job-432;rows=32;columns=256;kind=1;infrac=10;activation=1;stage=SAT_EMBED_AFFINE;
            for(int i=0;i<256;i++)vector[i]=point[i*27+t];
        }else{
            t=(job-459)/4;sub=(job-459)%4;
            if(sub==0){
                rows=144;columns=32;kind=2;infrac=10;activation=0;stage=SAT_GRU_INPUT_AFFINE;
                for(int i=0;i<32;i++)vector[i]=embedding[t*32+i];
            }else{
                rows=sub==1?144:(sub==2?126:63);columns=48;kind=sub==1?3:(sub==2?4:5);
                infrac=14;activation=sub==2?2:0;
                stage=sub==1?SAT_GRU_HIDDEN_AFFINE:(sub==2?SAT_PHASE_AFFINE:SAT_SUPPORT_AFFINE);
                for(int i=0;i<48;i++)vector[i]=h[i];
            }
        }
        matrix12(vector,result,rows,columns,kind,infrac,stats,stage,activation);
        if(job<432){
            for(int c=0;c<16;c++)point[(c*16+f)*27+t]=result[c];
        }else if(job<459){
            for(int c=0;c<32;c++)embedding[t*32+c]=result[c];
        }else if(sub==0){
            for(int g=0;g<144;g++)input_gate[g]=result[g];
        }else if(sub==1){
            for(int g=0;g<144;g++)hidden_gate[g]=result[g];
            for(int c=0;c<48;c++){
                const i16 reset_pre=sat(i32(input_gate[c])+hidden_gate[c],stats,SAT_GRU_RESET_PRE);
                const i16 update_pre=sat(i32(input_gate[48+c])+hidden_gate[48+c],stats,SAT_GRU_UPDATE_PRE);
                const i32 r=sigmoid(reset_pre,stats),z=sigmoid(update_pre,stats);
                const i16 new_pre=sat(i32(input_gate[96+c])+round_shift(i64(r)*hidden_gate[96+c],15),stats,SAT_GRU_NEW_PRE);
                const i16 n=tanh_q14(new_pre,stats);
                next_h[c]=sat(i32(n)+round_shift(i64(z)*(i32(h[c])-n),15),stats,SAT_GRU_HIDDEN);
            }
            for(int c=0;c<48;c++){h[c]=next_h[c];hidden[t*48+c]=h[c];}
        }else if(sub==2){
            for(int c=0;c<126;c++)phase[c*27+t]=result[c];
        }else{
            for(int k=0;k<63;k++)support[k*27+t]=result[k];
        }
    }
}
'''
source=source[:start]+pair+source[end:]
source=source.replace('srpdnn_forward_v2(', 'srpdnn_forward_v3(')
(V/'srpdnn_v3.cpp').write_text(source)
runner=(P/'variant2/run_v2.cpp').read_text().replace('srpdnn_forward_v2','srpdnn_forward_v3')
(V/'run_v3.cpp').write_text(runner)
r=subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-std=c++17','-fno-fast-math',str(V/'srpdnn_v3.cpp'),str(V/'run_v3.cpp'),'-o',str(V/'v3.exe')],capture_output=True,text=True)
(V/'compile.log').write_text(r.stdout+r.stderr);r.check_returncode()
rows=[]
for kind in ['speech','broad']:
    inp=F/f'room0_{kind}_input_q11.bin';out=V/f'{kind}_output_q.bin';stats=V/f'{kind}_stats.txt';start=time.perf_counter()
    subprocess.run([str(V/'v3.exe'),str(inp),str(out),str(stats)],check=True)
    assert out.read_bytes()==(F/f'room0_{kind}_output_q.bin').read_bytes(),kind
    assert stats.read_text().split()==(F/f'room0_{kind}_stats.txt').read_text().split(),kind
    rows.append(dict(kind=kind,comparedOutputInt16=len(out.read_bytes())//2,allOutputBitExact=True,all18CountersExact=True,CPUSeconds=time.perf_counter()-start))
(V/'C_EQUIVALENCE.json').write_text(json.dumps(dict(status='PASS',rows=rows,fullNetwork10HzVerified=False),indent=2))
print('VARIANT3_C_BITEXACT_PASS',len(rows),'full15pair cases')
