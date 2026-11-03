from pathlib import Path
import ctypes,sys,json
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'))
from das_map import power_map,install
from manual_das import MIC
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*3+[ctypes.c_void_p]
mem=np.zeros(720000,np.float32);fs=48009.775390625;c0=343.42;points=[(0,0),(90,0),(180,0),(270,0),(0,90),(0,-90)];freq=np.arange(100,104)*fs/2048
true=np.array([1.,0,0]);M=np.array(MIC);X=np.exp(2j*np.pi*freq[None,:]*(M@true)[:,None]/c0)*30
for ch in range(6):
 mem[262144+ch*8192+200:262144+ch*8192+208:2]=X[ch].real;mem[262144+ch*8192+201:262144+ch*8192+208:2]=X[ch].imag
code=power_map(points,first=100,count=4);s=install(mem,code)
for k in range(10000):
 st=ctypes.c_uint();fn(mem.ctypes.data,s['descriptor'],len(mem),0,ctypes.byref(st));assert not st.value&255,hex(st.value)
 if st.value>>31:break
else:raise AssertionError('timeout')
gold=[]
for az,el in points:
 az,el=np.radians([az,el]);v=np.array([np.cos(el)*np.cos(az),np.cos(el)*np.sin(az),np.sin(el)]);a=np.exp(2j*np.pi*freq[None,:]*(M@v)[:,None]/c0);y=np.sum(a.conj()*X,axis=0)/6;gold.append(np.sum(abs(y)**2*2/(fs*768)*fs/2048))
a=mem[s['output']+8192:s['output']+8192+len(points)];np.testing.assert_allclose(a,gold,rtol=3e-4,atol=1e-7)
u=mem.view(np.uint32);peaks=[u[s['output']+10240+3*i] for i in range(3)];assert peaks[0]==int(np.argmax(gold));assert len(set(peaks))==3;np.testing.assert_array_equal(mem[s['output']+10242:s['output']+10249:3],1)
(p/'results/das_map_native.json').write_text(json.dumps(dict(nativeOnly=True,directions=len(points),frequencyBins=4,comparedPowers=6,peakIndices=[int(i) for i in peaks],chunks=k+1,instructions=len(code[0].words),automaticDOA=False),indent=2));print('DAS_MAP_NATIVE_PASS 6directions beam-power NMS3 PL-angle-generation')
