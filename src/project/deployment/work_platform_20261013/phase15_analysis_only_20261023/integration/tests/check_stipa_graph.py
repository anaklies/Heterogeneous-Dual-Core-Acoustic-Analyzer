from pathlib import Path
import sys,ctypes,json
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from stipa_graph import *
from deployment_profiles import build_profile
assert len(graph())==101 and sum(d['kind']=='fit' for d in graph())==84
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native_meta;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*8+[ctypes.c_void_p]
rows=[]
for confirmed in (True,False):
 m=np.zeros(4194304,np.float32);s=install_graph_stage(m,100,confirmed=confirmed,session=3,config=7,generation=100);q=old.layout(720000);out=s['output'];m[out+q['result']+31]=1
 for b in range(7):
  for trace,depth in [(0,.5),(1,.3)]:
   m[out+q['result']+32+2*b+trace]=1;at=out+q['result']+48+trace*42+b*6;m[at:at+6]=[1,0,depth,0,depth,0]
 for k in range(100):
  st=ctypes.c_uint();fn(m.ctypes.data,TABLE,len(m),0,3,7,50,102400,0,ctypes.byref(st));assert not st.value&255,hex(st.value)
  if st.value>>31:break
 else:raise AssertionError('timeout')
 if confirmed:np.testing.assert_allclose(m[out:out+3],[(10*np.log10(1.5)+15)/30,1,0],rtol=1e-5,atol=1e-6)
 else:np.testing.assert_array_equal(m[out:out+3],[0,0,0])
 patches=stage_patch(m,s);assert all(a>=524288 for a,_ in patches);rows.append(dict(confirmed=confirmed,chunks=k+1,estimate=float(m[out]),valid=float(m[out+1]),certified=float(m[out+2])))
m,j=build_profile('stipa',{'n':720000,'confirmed':True},session=3,config=7);assert not j['config32'][8]&2 and j['config32'][31]==1
(p/'results/stipa_graph_native.json').write_text(json.dumps(dict(nativeOnly=True,fullWaveformGraphRun=False,stages=101,staticTopologyAndFinalGlueTested=True,cases=rows),indent=2));print('STIPA_GRAPH_NATIVE_PASS 101-stage topology final-glue valid/invalid; full waveform not rerun')
