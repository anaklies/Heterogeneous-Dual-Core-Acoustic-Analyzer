from pathlib import Path
import ctypes,json,subprocess,hashlib
import numpy as np
P=Path(__file__).resolve().parents[1];H=P/'hls'
def literal(v):
    s=format(float(np.float32(v)),'.9g')
    return s+('f' if '.' in s or 'e' in s else '.0f')
t=np.arange(1536)*2*np.pi/1536
arrays=dict(FFT1536_COS=np.cos(t),FFT1536_SIN=-np.sin(t),FFT1536_HANN=.5-.5*np.cos(t))
rom='// Deterministicfloat32 constants; no lookup interpolation.\n'
for name,v in arrays.items():rom+=f'static const float {name}[1536]={{'+','.join(map(literal,v))+'};\n'
(H/'fft1536_rom.h').write_text(rom)
subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-shared',str(H/'fft1536.cpp'),'-o',str(H/'fft1536.dll')],check=True)
fn=ctypes.CDLL(str(H/'fft1536.dll')).fft1536_hann
fn.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
rng=np.random.default_rng(132123);rows=[]
for i in range(20):
    x=rng.normal(0,.01,1536).astype(np.float32) if i<10 else (.01*np.sin(2*np.pi*(i-9)*123.4*np.arange(1536)/48000)).astype(np.float32)
    out=np.zeros(1538,np.float32);fn(x.ctypes.data,out.ctypes.data)
    z=out[::2]+1j*out[1::2];gold=np.fft.rfft(x*arrays['FFT1536_HANN'])
    error=float(np.max(abs(z-gold)));assert np.allclose(z,gold,atol=3e-6,rtol=2e-4), (i,error)
    rows.append(dict(case=i,maxComplexAbsoluteError=error,inputSHA256=hashlib.sha256(x.tobytes()).hexdigest()))
result=dict(cases=20,complexBinsCompared=20*769,rows=rows,maximumAbsoluteError=max(r['maxComplexAbsoluteError'] for r in rows),
    model='1536point,periodicHann,noDCremoval,noFFTscaling',hardwareRTLValidated=False)
(P/'tests/fft1536_numeric.json').write_text(json.dumps(result,indent=2))
print('FFT1536_C_NUMERIC_PASS',result['complexBinsCompared'],result['maximumAbsoluteError'])
