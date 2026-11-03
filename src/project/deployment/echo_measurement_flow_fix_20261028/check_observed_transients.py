import ctypes,sys,json
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;S=R.parents[1]/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services';sys.path.insert(0,str(S))
import p2_chains as chain
from impulse_producers import impulse_capture_prepare
fn=ctypes.CDLL(str(R/'room_native.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
rng=np.random.default_rng(883);n=24000;rows=[]
for name in ['background_only','speaker_impulse']:
 y=np.fromfile(R/'observed_initial'/(name+'.bin'),'<f4')[32:24032];x=np.concatenate([y,np.zeros(n)])
 c,meta=impulse_capture_prepare(n,stimulus_confirmed=True);m=np.zeros(1200000,np.float32);sp=chain.install(m,(c,meta),base=1048576);u=m.view(np.uint32);u[sp['output']+32:sp['output']+32+2*n]=np.asarray(np.rint(x*8388608),np.int32).view(np.uint32)
 for slot in range(4):u[1048576+slot*16+8]=32+2*n
 for k in range(100000):
  st=ctypes.c_uint();fn(m.ctypes.data,sp['descriptor'],len(m),0,ctypes.byref(st))
  assert st.value&255==0,hex(st.value)
  if st.value&0x80000000:break
 valid=bool(m[sp['output']+30]);rows.append({'case':name,'valid':valid,'onsetIndex':int(u[sp['output']+28]),'peak':float(m[sp['output']+29]),'blockEnergy':float(m[sp['output']+31])})
(R/'OBSERVED_TRANSIENT_GATE.json').write_text(json.dumps(rows,indent=2));print(rows)
