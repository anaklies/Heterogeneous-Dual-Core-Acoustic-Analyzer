from pathlib import Path
import ctypes,sys,json
import numpy as np
from scipy.signal import sosfilt
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from room_services import install_room
from room_band_decay import band_decay
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*3+[ctypes.c_void_p]
n=8192;fs=48000;rng=np.random.default_rng(1224);x=(rng.normal(size=n)*np.exp(-np.arange(n)/fs*6.908/.12)).astype(np.float32);reports=[]
for fc in (500,1000,2000):
 mem=np.zeros(1200000,np.float32);code=band_decay(n,fs,fc);spec=install_room(mem,code,ir=x)
 for chunks in range(1,50000):
  st=ctypes.c_uint();fn(mem.ctypes.data,spec['descriptor'],len(mem),0,ctypes.byref(st));assert not st.value&255,hex(st.value)
  if st.value>>31:break
 else:raise AssertionError('timeout')
 out=spec['output'];actual=mem[out+32:out+32+n];gold=sosfilt(np.array(code[2]['sos']),x.astype(float))
 # Quantized DF2T in a narrow band is judged against signal scale, not tail zeros.
 err=np.max(abs(actual-gold));assert err<3e-4*max(abs(gold)),(fc,err,max(abs(gold)))
 decay=10*np.log10(np.maximum(np.cumsum(actual.astype(float)[::-1]**2)[::-1]/np.sum(actual.astype(float)**2),1e-30))
 np.testing.assert_allclose(mem[out+code[2]['decay_offset']:out+code[2]['decay_offset']+n],decay,atol=.002,rtol=1e-5)
 reports.append(dict(center=fc,filteredValues=n,decayValues=n,chunks=chunks,max_abs_filter_error=float(err),instructions=len(code[0].words)))
(p/'results/room_bands_native.json').write_text(json.dumps(dict(nativeOnly=True,cases=reports),indent=2));print('ROOM_BANDS_NATIVE_PASS 3 bands 49152 values SOS plus real room chain')
