"""Short native equivalence checks against NumPy; no RTL acceptance claim."""
from pathlib import Path
import ctypes,json
import numpy as np
from programs import *

HERE=Path(__file__).resolve().parent
fn=ctypes.CDLL(str(HERE/'services_scalar.dll')).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
rng=np.random.default_rng(831)
memory=np.zeros(700000,np.float32)
reports=[]

def spectrum(slot,values):
    start=262144+slot*65536
    memory[start+4096:start+7171:3]=np.sqrt(values)
    memory[start+4097:start+7171:3]=values/23.4375
    memory[start+4098:start+7171:3]=values

def run(spec,slot=0):
    for chunks in range(1,3000):
        status=ctypes.c_uint()
        fn(memory.ctypes.data,spec['descriptor']+slot*16,len(memory),slot,ctypes.byref(status))
        assert status.value&255==0,hex(status.value)
        if status.value&0x80000000: break
    else: raise AssertionError('program did not terminate')
    actual=memory[spec['output']:spec['output']+spec['output_words']].copy()
    assert np.isfinite(actual).all()
    return actual,chunks

def check(name,actual,expected,chunks,rtol=3e-5,atol=1e-8):
    np.testing.assert_allclose(actual,expected,rtol=rtol,atol=atol)
    reports.append(dict(service=name,compared=int(np.size(expected)),chunks=chunks,
                        max_absolute_error=float(np.max(np.abs(actual-expected)))))

x=rng.random(1025).astype(np.float32)*.1
y=rng.random(1025).astype(np.float32)*.15
spectrum(0,x);spectrum(1,y)
for kind in ('copy','peak_hold','ema'):
    spec=install(memory,vector(kind))
    a,k=run(spec)
    initial=x*.2 if kind=='ema' else x
    check(kind+'_first',a,initial,k)
    a,k=run(spec,1)
    gold=y if kind=='copy' else np.maximum(x,y) if kind=='peak_hold' else initial*.8+y*.2
    check(kind+'_cross_slot',a,gold,k)

spec=install(memory,smoothing());a,k=run(spec)
gold=x.copy();gold[1:-1]=(x[:-2]+2*x[1:-1]+x[2:])*.25
check('smoothing',a,gold,k)
for fraction in (1,3):
    spec=install(memory,band_sums(48000,fraction));a,k=run(spec)
    gold=np.array([np.sum(x[lo:hi],dtype=np.float64) for lo,hi in spec['metadata']['bin_ranges']])
    check('octave_'+str(fraction),a,gold,k)
spec=install(memory,shape(48000));a,k=run(spec)
v=x[1:];freq=np.arange(1,1025)*23.4375
gold=[np.sum(v*freq)/np.sum(v),np.exp(np.mean(np.log(np.maximum(v,1e-20))))/np.mean(v),np.max(v),freq[np.argmax(v)]]
check('shape',a,gold,k,rtol=1e-4)
spec=install(memory,difference());a,k=run(spec)
check('flux_initial',a[:3],[x.sum(),x.sum(),np.sqrt(np.mean(x*x))],k)
a,k=run(spec,1);d=y-x
check('flux_cross_slot',a[:3],[np.maximum(d,0).sum(),np.abs(d).sum(),np.sqrt(np.mean(d*d))],k)
np.testing.assert_array_equal(a[3:],y)

# Quiet spectrum and a single non-DC peak check numerical floor and peak units.
for signal in (np.zeros(1025,np.float32),np.eye(1,1025,123,dtype=np.float32).ravel()):
    spectrum(2,signal);spec=install(memory,shape(48000));a,k=run(spec,2)
    if signal.any():
        check('shape_single_tone',a[[0,2,3]],[123*23.4375,1,123*23.4375],k)
    else:
        check('shape_silence',a[[0,2,3]],[0,0,0],k)
        assert abs(a[1]-1)<1e-4 # numerical floor only; silence is not a valid shape observation

# Descriptor/version isolation and protected slot identity retain core safeguards.
spec=install(memory,vector('copy',count=4));spectrum(0,x)
u=memory.view(np.uint32);u[spec['descriptor']+9]=1
status=ctypes.c_uint();fn(memory.ctypes.data,spec['descriptor'],len(memory),0,ctypes.byref(status))
u[spec['descriptor']+10]=0;u[spec['descriptor']+14]+=1
fn(memory.ctypes.data,spec['descriptor'],len(memory),0,ctypes.byref(status));assert status.value==3
reports.append(dict(service='generation_mismatch_rejected',status=3))
result=dict(verification='Native scalar C versus independent NumPy, not HLS/RTL or board timing',
            cases=reports,total_compared=sum(r.get('compared',0) for r in reports))
(HERE/'NATIVE_RESULTS.json').write_text(json.dumps(result,indent=2))
print('P1_SERVICES_NATIVE_PASS cases=',len(reports),'values=',result['total_compared'])
