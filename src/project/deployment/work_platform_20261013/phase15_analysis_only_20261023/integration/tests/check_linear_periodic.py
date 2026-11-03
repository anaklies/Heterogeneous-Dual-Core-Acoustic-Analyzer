from pathlib import Path
import ctypes,sys,json
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from linear_periodic import linear_correlation,fundamental,install
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*3+[ctypes.c_void_p]
m=np.zeros(720000,np.float32);u=m.view(np.uint32);rng=np.random.default_rng(1624);rows=[]
def run(program,x,y=None):
 x=np.asarray(x,np.int32);u[:1024]=x.view(np.uint32)
 if y is not None:u[2048:3072]=np.asarray(y,np.int32).view(np.uint32)
 s=install(m,program);requests=[]
 for k in range(30000):
  st=ctypes.c_uint();fn(m.ctypes.data,s['descriptor'],len(m),0,ctypes.byref(st));v=st.value;assert not v&255,hex(v)
  if v&0x40000000:
   mode=(v>>28)&3;out=((v>>18)&1023)<<12;assert out==s['output'];z=m[out+4096:out+8192:2].astype(float)+1j*m[out+4097:out+8192:2]
   z=np.fft.fft(z) if mode==1 else np.fft.ifft(z);m[out+8192:out+12288:2]=z.real;m[out+8193:out+12288:2]=z.imag;requests.append(mode)
  if v>>31:break
 else:raise AssertionError('timeout')
 return m[s['output']:s['output']+s['metadata']['output_count']].copy(),k+1,requests
x=rng.integers(-2000000,2000001,1024,dtype=np.int32);y=np.r_[np.zeros(7,np.int32),x[:-7]]
for other in (None,1):
 a,k,r=run(linear_correlation(other=other),x,y);xx=x.astype(float)/8388608;xx-=xx.mean();yy=xx if other is None else y.astype(float)/8388608-y.astype(float).mean()/8388608
 z=np.correlate(xx,yy,'full');gold=np.r_[z[1023:],0,z[:1023]]
 np.testing.assert_allclose(a,gold,rtol=3e-5,atol=2e-6);rows.append(dict(service='linear_auto' if other is None else 'linear_cross',compared=2048,chunks=k,FFTrequests=r,maxAbsoluteError=float(max(abs(a-gold)))))
a,k,r=run(linear_correlation(other=1,phat=True),y,x);assert np.argmax(a)==7;rows.append(dict(service='linear_phat_delay',samples=7,chunks=k,FFTrequests=r))
fs=48009.775390625
for hz in (200,400,900):
 x=np.round(1e6*np.sin(2*np.pi*hz*np.arange(1024)/fs)).astype(np.int32);a,k,r=run(fundamental(),x);assert a[2050]==1 and abs(a[2048]-hz)<2,(hz,a[-3:]);rows.append(dict(service='fundamental',truthHz=hz,estimatedHz=float(a[2048]),chunks=k,FFTrequests=r))
a,k,r=run(fundamental(),np.zeros(1024,np.int32));assert a[2048]==0 and a[2050]==0;rows.append(dict(service='fundamental_silence_invalid',chunks=k))
(p/'results/linear_periodic_native.json').write_text(json.dumps(dict(nativeOnly=True,FFTsyscallUsesNumPyGolden=True,cases=rows),indent=2));print('LINEAR_PERIODIC_NATIVE_PASS auto/cross4096 PHATdelay 3tones silence-invalid')
