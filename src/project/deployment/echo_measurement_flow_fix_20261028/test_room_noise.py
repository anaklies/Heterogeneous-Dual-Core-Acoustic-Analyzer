import ctypes,sys,time,json,math,importlib.util
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parent;S=R.parents[1]/'deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/services';sys.path.insert(0,str(S))
import room_services as old
import room_noise_compensated as new
fn=ctypes.CDLL(str(R/'room_native.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
def run(module,x):
 m=np.zeros(1200000,np.float32);sp=module.install_room(m,module.room_ir(len(x),48000),ir=x);t=time.perf_counter()
 for k in range(200000):
  st=ctypes.c_uint();fn(m.ctypes.data,sp['descriptor'],len(m),0,ctypes.byref(st))
  if st.value&255:raise ValueError(hex(st.value))
  if st.value&0x80000000:break
 else:raise ValueError('timeout')
 a=m[sp['output']:sp['output']+sp['output_words']];return {'fits':[float(a[i]) if a[i+2] else None for i in [10,16,22]],'noisePower':float(a[9]),'noiseLimitDb':float(a[28]),'seconds':time.perf_counter()-t},a
rng=np.random.default_rng(9182);fs=48000;n=24000;t=np.arange(n)/fs;rows=[]
for name,rt,noise in [('clean_03',.3,0),('noise_03',.3,.0001),('noise_06',.6,.0001),('insufficient_snr',.6,.03),('background',None,.002),('silence',None,0)]:
 x=(.2*np.exp(-math.log(1000)*t/rt)*rng.normal(size=n) if rt else np.zeros(n))+noise*rng.normal(size=n)
 a,_=run(old,x);b,y=run(new,x);rows.append({'case':name,'rt60':rt,'old':a,'new':b});print(name,a['fits'],'->',b['fits'],flush=True)
 if name=='noise_03':assert b['fits'][1] is not None and abs(b['fits'][1]-.3)<.05
 if name in ('background','silence'):assert all(v is None for v in b['fits'])
(R/'ROOM_NOISE_NATIVE.json').write_text(json.dumps(rows,indent=2))

