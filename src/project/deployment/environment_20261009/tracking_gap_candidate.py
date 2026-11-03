from pathlib import Path
import subprocess,json,ctypes,os
import numpy as np
P=Path(__file__).resolve().parent;F=P.parents[2]/'sixmic3D_fpga';H=F/'pl/hls'
before=(P.parents[1]/'deployment/tracking_recovery_20261009/candidate.cpp').read_text();candidate=before
candidate=candidate.replace('''t.v[c] *= .5f;
        t.du[c] *= .5f;''','''if (t.haspos) t.p[c] = pred[i][c];
        t.v[c] *= .8f;
        t.u[c] = predU[i][c];
        t.du[c] *= .8f;''')
candidate=candidate.replace('if (t.miss > 3)','if (t.miss > (t.hits >= 2 ? 6 : 3))')
candidate=candidate.replace('if (!t.range) {','if (!t.range || t.miss > 0) {')
candidate=candidate.replace('tracks[i].observed[c] + tracks[i].du[c] * dt;', '(tracks[i].miss > 0 ? tracks[i].u[c] : tracks[i].observed[c]) + tracks[i].du[c] * dt;')
candidate=candidate.replace('(dir[di][c] - t.observed[c]) / dt;', '''(dir[di][c] - t.observed[c]) / dt;
      // Seven bounded inter-observation intervals; avoid a second variable
      // float conversion/divisor circuit, retaining the same correction.
      float inverse_interval = 1.f;
      switch (t.miss) {
      case 1: inverse_interval=.5f;break;
      case 2: inverse_interval=.3333333333333333f;break;
      case 3: inverse_interval=.25f;break;
      case 4: inverse_interval=.2f;break;
      case 5: inverse_interval=.1666666666666667f;break;
      case 6: inverse_interval=.1428571428571429f;break;
      }
      for(int c=0;c<3;c++)rate[c]*=inverse_interval;''')
assert candidate!=before
(P/'tracker_before.cpp').write_text(before);(P/'tracker_gap_candidate.cpp').write_text(candidate)
bridge='''#include <stdint.h>
extern void track_sources(const int32_t*,float,bool,int32_t*);
extern void track_sources_candidate(const int32_t*,float,bool,int32_t*);
extern "C" __declspec(dllexport) void before(const int32_t*i,float d,bool r,int32_t*o){track_sources(i,d,r,o);}
extern "C" __declspec(dllexport) void candidate(const int32_t*i,float d,bool r,int32_t*o){track_sources_candidate(i,d,r,o);}
'''
(P/'gap_bridge.cpp').write_text(bridge)
cxx='D:/mingw64/bin/g++.exe'
for name in ['tracker_before','tracker_gap_candidate']:
    cmd=[cxx,'-O2','-c',str(P/(name+'.cpp')),'-I',str(H),'-o',str(P/(name+'.o'))]
    if name.endswith('candidate'):cmd+=['-Dtrack_sources=track_sources_candidate']
    subprocess.run(cmd,check=True)
subprocess.run([cxx,'-shared',str(P/'gap_bridge.cpp'),str(P/'tracker_before.o'),str(P/'tracker_gap_candidate.o'),'-o',str(P/'gap_tracking.dll')],check=True)
os.add_dll_directory('D:/mingw64/bin');lib=ctypes.CDLL(str(P/'gap_tracking.dll'));ptr=np.ctypeslib.ndpointer(dtype=np.int32,flags='C_CONTIGUOUS')
for fn in [lib.before,lib.candidate]:fn.argtypes=[ptr,ctypes.c_float,ctypes.c_bool,ptr]
results={}
for name,fn in [('before',lib.before),('candidate',lib.candidate)]:
    changes=0;misses=0;errors=[];leaks=0
    for count in [1,2,3]:
        for seed in [613001,613002,613003]:
            rng=np.random.default_rng(seed);ids={}
            for f in range(80):
                truth=np.array([[.4+.1*f,1,.2],[-1,.4+.06*f,.3],[.2,-1.5,.1]])[:count]
                raw=np.zeros(52,np.int32);available=[]
                for t,p in enumerate(truth):
                    if t==0 and f in [20,21,22,23,24,50,51,52,53,54]:continue
                    available.append((t,p+rng.normal(0,.003,3)))
                available=available[::-1] if f%2 else available;raw[0]=len(available)
                for d,(t,p) in enumerate(available):
                    b=7+15*d;raw[b]=d+1;raw[b+1]=1;raw[b+2:b+5]=np.rint(p/np.linalg.norm(p)*65536).astype(np.int32);raw[b+5:b+8]=np.rint(p*65536).astype(np.int32)
                out=np.zeros(52,np.int32);fn(raw,.25,f==0,out)
                for t,p in enumerate(truth):
                    valid=[i for i in range(out[0]) if out[8+15*i] and not out[18+15*i]]
                    if not any(tt==t for tt,_ in available):
                        if valid and min(np.linalg.norm(out[12+15*i:15+15*i]/65536-p) for i in valid)<.12:leaks+=1
                        continue
                    if not valid:misses+=1;continue
                    e=min(valid,key=lambda i:np.linalg.norm(out[12+15*i:15+15*i]/65536-p));error=np.linalg.norm(out[12+15*e:15+15*e]/65536-p)
                    if error>.3:misses+=1;continue
                    identity=int(out[7+15*e]);errors.append(error*100)
                    if t in ids and ids[t]!=identity:changes+=1
                    ids[t]=identity
    results[name]={'IDchanges':changes,'missingFreshTargets':misses,'meanFreshErrorCm':float(np.mean(errors)),'maxFreshErrorCm':max(errors),'freshCoordinateLeaksDuringSilence':leaks}
(P/'tracking_gap_comparison.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
