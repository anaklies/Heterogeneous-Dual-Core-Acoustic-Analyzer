"""Final bounded memory/copy repair. Same integer math, no new model."""
from pathlib import Path
import json,subprocess,time,re,csv
P=Path(__file__).resolve().parent;V=P/'variant4';V.mkdir(exist_ok=True);F=P.parent/'fixed'
(V/'matrix_weights.h').write_bytes((P/'variant3/matrix_weights.h').read_bytes())
source=(P/'variant3/srpdnn_v3.cpp').read_text()
begin=source.index('static void convolution12(');end=source.index('// One lexicalcall',begin)
conv=source[begin:end]
tail='''    for(int i=0;i<12*32*27;i++) {
#pragma HLS PIPELINE II=1
        external_output[i]=results[i];
    }
'''
assert tail in conv
conv=conv.replace(tail,'').replace('    i16 results[12*32*27];\n','').replace('#pragma HLS BIND_STORAGE variable=results type=ram_s2p impl=bram\n','')
conv=conv.replace('results[(lane*32+f)*27+t]','external_output[(lane*32+f)*27+t]')
source=source[:begin]+conv+source[end:]
begin=source.index('static void pair_forward(');end=source.index('extern "C" void srpdnn_forward_v3',begin)
pair=source[begin:end]
def pipeline(m):
    indent,loop,body=m.groups()
    return f'{indent}for({loop}){{\n#pragma HLS PIPELINE II=1\n{indent}    {body}\n{indent}}}'
pair,count=re.subn(r'(?m)^( *)for\((int [^\n)]*)\)([^{}\n]+;)$',pipeline,pair)
old='for(int c=0;c<48;c++){h[c]=next_h[c];hidden[t*48+c]=h[c];}'
new='for(int c=0;c<48;c++){\n#pragma HLS PIPELINE II=1\n                h[c]=next_h[c];hidden[t*48+c]=h[c];\n            }'
assert old in pair;pair=pair.replace(old,new)
source=source[:begin]+pair+source[end:]
source=source.replace('srpdnn_forward_v3(', 'srpdnn_forward_v4(')
(V/'srpdnn_v4.cpp').write_text(source)
runner=(P/'variant3/run_v3.cpp').read_text().replace('srpdnn_forward_v3','srpdnn_forward_v4')
(V/'run_v4.cpp').write_text(runner)
r=subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-std=c++17','-fno-fast-math',str(V/'srpdnn_v4.cpp'),str(V/'run_v4.cpp'),'-o',str(V/'v4.exe')],capture_output=True,text=True)
(V/'compile.log').write_text(r.stdout+r.stderr);r.check_returncode()
rows=[]
for kind in ['speech','broad']:
    inp=F/f'room0_{kind}_input_q11.bin';out=V/f'{kind}_output_q.bin';stats=V/f'{kind}_stats.txt';start=time.perf_counter()
    subprocess.run([str(V/'v4.exe'),str(inp),str(out),str(stats)],check=True)
    assert out.read_bytes()==(F/f'room0_{kind}_output_q.bin').read_bytes(),kind
    assert stats.read_text().split()==(F/f'room0_{kind}_stats.txt').read_text().split(),kind
    rows.append(dict(kind=kind,comparedOutputInt16=len(out.read_bytes())//2,allOutputBitExact=True,all18CountersExact=True,CPUSeconds=time.perf_counter()-start))
(V/'C_EQUIVALENCE.json').write_text(json.dumps(dict(status='PASS',rows=rows,pipelinedCopyLoops=count+1,fullNetwork10HzVerified=False),indent=2))
descriptors=[]
for job in range(567):
    if job<432:kind='point';rows_,cols=16,12
    elif job<459:kind='embedding';rows_,cols=32,256
    else:
        kind=['gru_input','gru_hidden','phase','support'][(job-459)%4]
        rows_,cols=[(144,32),(144,48),(126,48),(63,48)][(job-459)%4]
    groups=(rows_+11)//12
    descriptors.append(dict(job=job,kind=kind,rows=rows_,columns=cols,groups=groups,
                            MACIssueCycles=groups*cols,derivedMatrixCycles=groups*(cols+34)+1))
with (V/'JOB_SCHEDULE.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(descriptors[0]));w.writeheader();w.writerows(descriptors)
schedule=dict(jobCount=len(descriptors),matrixMACIssueCycles=sum(d['MACIssueCycles'] for d in descriptors),
              derivedMatrixCycles=sum(d['derivedMatrixCycles'] for d in descriptors),
              formula='groups*(columns+34)+1 from V3matrix12HLS endpoints; must recheckV4report; not wholepaircycleproof',
              excludes=['conv','depth','copy/control','GRUnonlinear','input/outputAXI','full15pairglobalheads','FFT/features/decoder'])
(V/'STATIC_SCHEDULE.json').write_text(json.dumps(schedule,indent=2))
print('VARIANT4_C_BITEXACT_PASS',len(rows),'full15pair cases;copyLoops',count+1)
