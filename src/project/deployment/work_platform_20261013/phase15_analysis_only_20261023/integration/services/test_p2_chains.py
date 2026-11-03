"""Native microcode checks; NumPy services FFT request as GOLDEN ONLY, not PL proof."""
import ctypes,json,subprocess
from pathlib import Path
import numpy as np
from scipy.signal import hilbert
from p2_chains import *

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'shared_backend/scalar_engine.cpp'
DLL=HERE/'p2_scalar_native.dll'
assert 'op==23' in SOURCE.read_text(), 'parent opcode23 not present yet'
subprocess.run(['D:/mingw64/bin/g++.exe','-DSIXMIC_NATIVE','-std=c++17','-O2','-shared',str(SOURCE),'-o',str(DLL)],check=True)
fn=ctypes.CDLL(str(DLL)).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
memory=np.zeros(720000,np.float32); rng=np.random.default_rng(7311)
x=rng.normal(0,.15,(6,N)); win=np.hanning(N+1)[:-1]
x=(x-x.mean(axis=1,keepdims=True))*win
X=np.fft.fft(x,axis=1)
for ch in range(6):
    memory[262144+8192*ch:262144+8192*ch+4096:2]=X[ch].real
    memory[262144+8192*ch+1:262144+8192*ch+4096:2]=X[ch].imag
reports=[]

def run(spec):
    requests=[]
    for chunk in range(1,10000):
        s=ctypes.c_uint();fn(memory.ctypes.data,spec['descriptor'],len(memory),0,ctypes.byref(s))
        status=s.value
        assert status&255==0,hex(status)
        if status&0x40000000:
            mode=(status>>28)&3; out=((status>>18)&1023)<<12
            assert out==spec['output'];assert mode in (1,2)
            z=memory[out+4096:out+8192:2].astype(np.float64)+1j*memory[out+4097:out+8192:2]
            z=np.fft.ifft(z) if mode==2 else np.fft.fft(z)
            memory[out+8192:out+12288:2]=z.real
            memory[out+8193:out+12288:2]=z.imag
            requests.append(mode)
        if status&0x80000000:break
    else:raise AssertionError('no completion')
    return memory[spec['output']:spec['output']+spec['metadata']['output_count']].copy(),chunk,requests


def check(specification,gold,rtol=2e-4,atol=2e-6):
    spec=install(memory,specification);a,chunks,requests=run(spec)
    assert np.isfinite(a).all()
    np.testing.assert_allclose(a,gold,rtol=rtol,atol=atol)
    reports.append(dict(service=spec['metadata']['service'],values=len(a),instructions=spec['program_instructions'],
                        chunks=chunks,fft_modes=requests,max_absolute_error=float(np.max(abs(a-gold)))))

check(cepstrum(),np.fft.ifft(np.log(np.maximum(abs(X[0]),1e-10))).real)
check(correlation(),np.fft.ifft(abs(X[0])**2).real)
cross=X[0]*np.conj(X[1])
check(correlation(other=1),np.fft.ifft(cross).real)
check(correlation(other=1,phat=True),np.fft.ifft(cross/np.maximum(abs(cross),1e-20)).real)
env=abs(hilbert(x[0]))
check(envelope(),env)
check(envelope(spectrum=True),abs(np.fft.fft(env))[:1025],atol=2e-4)
# DC and Nyquist retained once; negative half suppressed. Constant and alternating
# records exercise the analytic-signal endpoint logic independently of random data.
for label,record in [('dc',np.ones(N)*.2),('nyquist',(-1.)**np.arange(N)*.2),('silence',np.zeros(N))]:
    z=np.fft.fft(record)
    memory[262144:266240:2]=z.real;memory[262145:266240:2]=z.imag
    check(envelope(),abs(hilbert(record)))
    reports[-1]['case']=label
    if label=='silence':
        check(correlation(other=0,phat=True),np.zeros(N))
        reports[-1]['case']='silent_phat'
result=dict(scope='Native scalar instruction execution with NumPy FFT-request golden emulation; NOT HLS/RTL/board acceptance',
            cases=reports,total_compared=sum(r['values'] for r in reports),
            implemented=['real cepstrum','circular autocorrelation','circular cross-correlation','GCC-PHAT correlation',
                         'Hilbert envelope','envelope spectrum'],
            limitations=['Windowed 2048-sample circular correlation, not unbiased long-lag correlation',
                         'No automatic DOA or XYZ','No multi-frame spectral kurtosis or STIPA service added here',
                         'FFT requests require actual PL scheduler source-slot ownership and completion fences',
                         'Long bounded microcode may span many P2 chunks; no real-time deadline claimed'])
(HERE/'P2_RESULTS.json').write_text(json.dumps(result,indent=2))
print('P2_CHAIN_NATIVE_PASS',len(reports),'cases',result['total_compared'],'values')
