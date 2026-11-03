from pathlib import Path
import ctypes,sys,json
import numpy as np
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'services'));from programs import install
from analysis_statistics import welch,compare
fn=ctypes.CDLL(str(p/'shared_backend/scalar.dll')).scalar_native;fn.argtypes=[ctypes.c_void_p]+[ctypes.c_uint]*3+[ctypes.c_void_p]
m=np.zeros(800000,np.float32);u=m.view(np.uint32);rng=np.random.default_rng(862)
def run(s,slot=0):
 for k in range(2000):
  st=ctypes.c_uint();fn(m.ctypes.data,s['descriptor']+16*slot,len(m),slot,ctypes.byref(st));assert not st.value&255,hex(st.value)
  if st.value>>31:return m[s['output']:s['output']+s['output_words']].copy(),k+1
 raise AssertionError('timeout')
s=install(m,welch());history=[]
for n in range(4):
 x=rng.random(1025).astype(np.float32)*1e-4;history.append(x);slot=n%4;m[262144+slot*65536+4097:262144+slot*65536+7171:3]=x
 a,k=run(s,slot);assert u[s['output']]==n+1;np.testing.assert_allclose(a[1:],np.mean(history,axis=0),rtol=3e-6,atol=1e-11)
s=install(m,compare(count=16,threshold=.01));start=750000;current=np.linspace(0,.2,16,dtype=np.float32);reference=current[::-1].copy();m[start:start+32]=np.r_[current,reference]
for slot in range(4):u[s['descriptor']+16*slot+5:s['descriptor']+16*slot+7]=[start,32]
a,k=run(s);np.testing.assert_allclose(a[:16],current-reference,atol=1e-8);np.testing.assert_array_equal(a[32:],np.abs(current-reference)>.01)
(p/'results/statistics_native.json').write_text(json.dumps(dict(nativeOnly=True,WelchDistinctFrames=4,PSDvalues=4100,comparisonValues=32),indent=2));print('STATISTICS_NATIVE_PASS Welch4100 AB_limit32')
