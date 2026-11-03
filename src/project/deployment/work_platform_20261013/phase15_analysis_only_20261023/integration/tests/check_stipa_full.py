from pathlib import Path
import ctypes,sys,json,time
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from stipa_graph import graph,install_graph_stage,TABLE
from stipa_offline import FS,CENTERS,PAIRS,layout
N=720000;t=np.arange(N)/FS
reference=np.zeros(N);observed=np.zeros(N)
for fc,(f1,f2) in zip(CENTERS,PAIRS):
 mod=np.sin(2*np.pi*f1*t)+np.sin(2*np.pi*f2*t)
 reference+=.035*np.sqrt(1+.4*mod)*np.sin(2*np.pi*fc*t)
 observed+=.035*np.sqrt(1+.2*mod)*np.sin(2*np.pi*fc*t)
raw=np.r_[np.round(reference*8388608),np.round(observed*8388608)].astype(np.int32)
m=np.zeros(4194304,np.float32);out=1048576+8192;m.view(np.uint32)[out:out+2*N]=raw.view(np.uint32)
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native_meta;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*8+[ctypes.c_void_p]
rows=[];started=time.perf_counter();limit=300;total_chunks=0
for index,d in enumerate(graph()):
 spec=install_graph_stage(m,index,n=N,confirmed=True,session=3,config=100+index,generation=index+1)
 stage_start=time.perf_counter()
 for k in range(10000000):
  status=ctypes.c_uint();fn(m.ctypes.data,TABLE,len(m),0,3,100+index,1000+index,2048*(1000+index),0,ctypes.byref(status));assert status.value&255==0,(index,hex(status.value))
  if status.value>>31:break
  if k%2048==0 and time.perf_counter()-started>limit:
   np.save(p/'results/stipa_native_checkpoint.npy',m);(p/'results/stipa_full_native.json').write_text(json.dumps(dict(status='INCOMPLETE_TIME_BUDGET',limitSeconds=limit,stage=index,totalStages=101,totalChunks=total_chunks+k,fullWaveformVerified=False),indent=2));print('STIPA_FULL_NATIVE_INCOMPLETE stage',index,flush=True);sys.exit(2)
 else:raise AssertionError('nontermination')
 total_chunks+=k+1;rows.append(dict(stage=index,kind=d['kind'],chunks=k+1,nativeSeconds=time.perf_counter()-stage_start))
 print('STIPA_STAGE',index,d['kind'],'chunks',k+1,flush=True)
actual=m[out:out+3].copy();assert actual[1]==1 and actual[2]==0,actual
assert abs(float(actual[0])-.5)<.08,actual
result=dict(status='PASS',fullWaveformVerified=True,nativeOnly=True,actualRTLWholeGraph=False,samplesPerTrace=N,nominalSampleRate=FS,stages=101,chunks=total_chunks,seconds=time.perf_counter()-started,index=float(actual[0]),expectedApproximateIndex=.5,valid=True,certified=False,rows=rows)
(p/'results/stipa_full_native.json').write_text(json.dumps(result,indent=2));print('STIPA_FULL_NATIVE_PASS',json.dumps({k:v for k,v in result.items()if k!='rows'}),flush=True)

