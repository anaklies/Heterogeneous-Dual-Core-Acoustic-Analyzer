from pathlib import Path
import ctypes,sys,json
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from noise_services import install_noise
from continuous_guard import checked_time_response
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native_meta;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*8+[ctypes.c_void_p]
m=np.zeros(700000,np.float32);m.view(np.uint32)[:2048]=np.full(2048,838861,np.int32).view(np.uint32)
s=install_noise(m,checked_time_response(48009.775390625));rows=[]
for frame,expected_valid,expected_count in [(10,0,2048),(11,1,4096),(20,0,2048),(21,1,4096),(21,0,4096)]:
 for k in range(1000):
  st=ctypes.c_uint();fn(m.ctypes.data,s['descriptor'],len(m),0,1,1,frame,frame*2048,0,ctypes.byref(st));assert not st.value&255,hex(st.value)
  if st.value>>31:break
 else:raise AssertionError('timeout')
 a=m[s['output']:s['output']+9];assert a[7]==expected_valid and a[2]==expected_count,(frame,a)
 rows.append(dict(frame=frame,valid=int(a[7]),processed_samples=int(a[2]),chunks=k+1))
(p/'results/time_continuity_native.json').write_text(json.dumps(dict(nativeOnly=True,cases=rows),indent=2));print('TIME_RESPONSE_CONTINUITY_PASS startup consecutive gap reset duplicate reject')
