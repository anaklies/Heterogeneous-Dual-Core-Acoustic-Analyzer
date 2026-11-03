from pathlib import Path
import ctypes,sys,json
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from programs import install
from frequency_drift import frequency_drift
m=np.zeros(700000,np.float32);fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native_meta
fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*8+[ctypes.c_void_p]
spec=install(m,frequency_drift(),session=3,config=7);checks=[];fs=48009.775390625
for frame,binno,delta,elapsed in [(100,40,0,0),(104,40,0,4),(110,42,2*fs/2048,6),(120,0,0,0),(124,43,0,0)]:
 m[262144+4098:262144+7171:3]=0;m[262144+4098+3*binno]=.02 if binno else 0
 for chunk in range(1000):
  s=ctypes.c_uint();fn(m.ctypes.data,spec['descriptor'],len(m),0,3,7,frame,frame*2048,0,ctypes.byref(s));assert not s.value&255,hex(s.value)
  if s.value>>31:break
 else:raise AssertionError('timeout')
 a=m[spec['output']:spec['output']+4];gold=[binno*fs/2048,delta,delta/(elapsed*2048/fs) if elapsed else 0,int(elapsed>0)]
 np.testing.assert_allclose(a,gold,rtol=1e-5,atol=1e-4);checks.append(dict(frame=frame,compared=4,chunks=chunk+1))
(p/'results/frequency_drift_native.json').write_text(json.dumps(dict(nativeOnly=True,cases=checks),indent=2));print('FREQUENCY_DRIFT_NATIVE_PASS 20 values skipped-frame timing silence invalidation')
