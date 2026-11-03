import ctypes,sys,json
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;S=R.parents[1]/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services';sys.path.insert(0,str(S))
import p2_chains as chain
from impulse_producers import impulse_capture_prepare
fn=ctypes.CDLL(str(R/'room_native.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
rng=np.random.default_rng(883);n=24000;rows=[]
for name,x,expected in [('silence',np.zeros(2*n),False),('noise',rng.normal(0,.002,2*n),False),('tone',.03*np.sin(np.arange(2*n)*2*np.pi*2000/48000),False),('impulse',rng.normal(0,.0001,2*n),True)]:
 if name=='impulse':x[6000:6050]+=.1*np.hanning(50)
 c,meta=impulse_capture_prepare(n,stimulus_confirmed=True);m=np.zeros(1200000,np.float32);sp=chain.install(m,(c,meta),base=1048576);u=m.view(np.uint32);u[sp['output']+32:sp['output']+32+2*n]=np.asarray(np.rint(x*8388608),np.int32).view(np.uint32)
 for slot in range(4):u[1048576+slot*16+8]=32+2*n
 for k in range(100000):
  st=ctypes.c_uint();fn(m.ctypes.data,sp['descriptor'],len(m),0,ctypes.byref(st))
  assert st.value&255==0,hex(st.value)
  if st.value&0x80000000:break
 valid=bool(m[sp['output']+30]);rows.append({'case':name,'valid':valid});assert valid==expected,(name,valid)
(R/'IMPULSE_GATE_NATIVE.json').write_text(json.dumps(rows,indent=2));print(rows)
