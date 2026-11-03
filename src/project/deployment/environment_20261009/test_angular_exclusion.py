from pathlib import Path
import subprocess,sys,ctypes,json
import numpy as np
P=Path(__file__).resolve().parent;F=P.parents[2]/'sixmic3D_fpga';H=F/'pl/hls'
sys.path.insert(0,str(F/'pl/baseline_20261008'))
from measure_algorithms import lib,scene,positions,call,evaluate
source=(H/'nearfield_music.cpp').read_text()
source=source.replace('''        if (evaluate)
            value = score_core(request[0], request[1], request[2], speed);''','''        if (evaluate) {
            value = score_core(request[0], request[1], request[2], speed);
            if(state!=14 && value<1e19f) {
                for(int old=0;old<target;old++) {
                    float dot=0;
                    for(int c=0;c<3;c++)dot+=scored_direction[c]*previous[old][c];
                    if(dot>.9781476007f)value=1e20f;
                }
            }
        }''')
(P/'music_angular_candidate.cpp').write_text(source)
(P/'music_angular_bridge.cpp').write_text('''#include <stdint.h>
extern void nearfield_music(const int64_t*,const int64_t*,const int64_t*,const int64_t*,const float*,const float*,int32_t*);
extern "C" __declspec(dllexport) void candidate_music(const int64_t*a,const int64_t*b,const int64_t*c,const int64_t*d,const float*e,const float*f,int32_t*g){nearfield_music(a,b,c,d,e,f,g);}
''')
subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-shared',str(P/'music_angular_candidate.cpp'),str(P/'music_angular_bridge.cpp'),'-I',str(H),'-o',str(P/'music_angular.dll')],check=True)
candidate=ctypes.CDLL(str(P/'music_angular.dll'));candidate.candidate_music.argtypes=lib.baseline_music.argtypes
def run(arr,cfg,mask):
    out=np.zeros(52,np.int32);candidate.candidate_music(*arr,mask,cfg,out);return out
records=[]
for index in range(60):
    count=1+index%3;r=[.75,1.25,2][(index//3)%3];snr=[6,18][(index//9)%2];reflection=[0,.2][(index//18)%2]
    truth=positions(r,count,640000+index);a,c,m=scene(truth,snr,reflection,640000+index,True)
    before,_=call(a,c,m);after=run(a,c,m)
    records.append({'kind':'ordinary','before':evaluate(before,truth),'candidate':evaluate(after,truth)})
for frame in range(40):
    az=np.array([-.6+.03*frame,.6-.03*frame]);el=np.array([.1,.14]);ds=np.array([1.2,1.5])
    truth=np.stack((ds*np.cos(el)*np.cos(az),ds*np.cos(el)*np.sin(az),ds*np.sin(el)),axis=1)
    a,c,m=scene(truth,12,.2,4000+frame,True);before,_=call(a,c,m);after=run(a,c,m)
    records.append({'kind':'crossing','before':evaluate(before,truth),'candidate':evaluate(after,truth)})
summary={}
for group in ['ordinary','crossing']:
    summary[group]={}
    for mode in ['before','candidate']:
        rows=[r[mode] for r in records if r['kind']==group];errs=[p['error_cm'] for r in rows for p in r['pairs'] if p['range_valid']]
        summary[group][mode]={'validMatched':len(errs),'within10cm':sum(e<=10 for e in errs),'meanCm':float(np.mean(errs)) if errs else None,
            'p95Cm':float(np.percentile(errs,95)) if errs else None,'maxCm':max(errs) if errs else None,
            'meanOspaCm':float(np.mean([r['ospa_cm_cap100'] for r in rows])),'extraDirections':sum(r['extra_directions'] for r in rows)}
(P/'angular_exclusion_comparison.json').write_text(json.dumps({'summary':summary,'cases':records},indent=2));print(json.dumps(summary,indent=2))
