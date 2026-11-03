from pathlib import Path
import ctypes,sys,json
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from programs import Code,install
from raw_conversion import convert_pcm24
lib=ctypes.CDLL(str(p/'shared_backend/scalar.dll'));fn=lib.scalar_native_meta;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*8+[ctypes.c_void_p]
m=np.zeros(700000,np.float32);u=m.view(np.uint32);c=Code();c.u(31,0)
for i in range(3):c.emit(26,i,imm=i);c.emit(21,i,31,imm=i,target=1)
c.emit(0);spec=install(m,(c,3,{}),session=3,config=7);status=ctypes.c_uint()
fn(m.ctypes.data,spec['descriptor'],len(m),0,3,7,123,0xffffff00,19,ctypes.byref(status));assert status.value&255==0,hex(status.value);assert u[spec['output']:spec['output']+3].tolist()==[123,0xffffff00,19]
spec=install(m,convert_pcm24(5,16),session=3,config=7);vals=np.array([-8388608,-1,0,1,8388607],np.int32);u[spec['output']+16:spec['output']+21]=vals.view(np.uint32)
for k in range(20):
 fn(m.ctypes.data,spec['descriptor'],len(m),0,3,7,124,2048,0,ctypes.byref(status));assert status.value&255==0,hex(status.value)
 if status.value>>31:break
else:raise AssertionError('timeout')
np.testing.assert_array_equal(m[spec['output']+16:spec['output']+21],vals.astype(np.float32)/8388608)
(p/'results/scalar_metadata.json').write_text(json.dumps(dict(nativeOnly=True,metadataWords=3,signedPCMExtremes=5,status='PASS'),indent=2));print('SCALAR_META_PCM_PASS metadata3 signedPCM5')
