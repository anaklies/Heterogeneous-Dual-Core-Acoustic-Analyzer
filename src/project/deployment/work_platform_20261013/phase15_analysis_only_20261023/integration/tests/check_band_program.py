from pathlib import Path
import ctypes,sys,json
import numpy as np
I=Path(__file__).resolve().parents[1];sys.path.insert(0,str(I/'shared_backend'))
from band_program import prepare_band,PRIVATE
m=np.zeros(PRIVATE+16384,np.float32)
actual=np.array([int(x,16) for x in (I/'tests/actual_fft.hex').read_text().split()],np.uint32).view(np.float32)
m[262144:262144+len(actual)]=actual
spec=prepare_band(m,48000,500,2000)
fn=ctypes.CDLL(str(I/'shared_backend/scalar.dll')).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
for chunks in range(1,100):
    status=ctypes.c_uint();fn(m.ctypes.data,PRIVATE,len(m),0,ctypes.byref(status))
    assert not status.value&255,hex(status.value)
    if status.value&0x80000000:break
else:raise AssertionError('bounded band program did not finish')
gold=np.sum(actual[4097+3*spec['first_bin']:4098+3*spec['last_bin']:3].astype(float))*48000/2048
value=float(m[spec['output']]);assert np.isclose(value,gold,rtol=2e-6,atol=1e-15),(value,gold)
r=dict(backend='native C same scalar source; not scalar RTL acceptance',input='actual production FFT RTL output',chunks=chunks,value=value,reference=gold,configuration=spec)
(I/'results/band_program.json').write_text(json.dumps(r,indent=2));print('PINNED_FFT_BAND_PROGRAM_PASS chunks=',chunks,'relative_power=',value)
