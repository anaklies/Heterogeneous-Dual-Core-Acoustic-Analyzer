from pathlib import Path
import sys,ctypes,json
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from recorded_time_response import recorded_time_response,install
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native_meta;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*8+[ctypes.c_void_p]
rows=[];N=8192;fs=49162010/1024;raw=838861
for contiguous in [True,False]:
 m=np.zeros(1300000,np.float32);s=install(m,recorded_time_response(N,fs,contiguous),base=1048576);m.view(np.uint32)[s['output']+32:s['output']+32+N]=raw
 for k in range(10000):
  st=ctypes.c_uint();fn(m.ctypes.data,s['descriptor'],len(m),0,1,1,10,20480,0,ctypes.byref(st));assert not st.value&255,hex(st.value)
  if st.value>>31:break
 else:raise AssertionError('timeout')
 a=m[s['output']:s['output']+9]
 if contiguous:
  power=(raw/8388608)**2;fast=power*(1-np.exp(-N/(fs*.125)));slow=power*(1-np.exp(-N/fs));np.testing.assert_allclose(a[[0,2]],[fast,slow],rtol=.001,atol=1e-7);assert abs(a[4]-10*np.log10(power))<.005 and a[6]==1
 else:assert a[6]==0
 rows.append(dict(contiguous=contiguous,valid=float(a[6]),chunks=k+1,FASTpower=float(a[0]),SLOWpower=float(a[2])))
(p/'results/recorded_time_response_native.json').write_text(json.dumps(dict(status='PASS',nativeOnly=True,liveContinuous=False,cases=rows),indent=2));print('RECORDED_TIME_RESPONSE_PASS exact FAST/SLOW Leq captured-continuity validation')
