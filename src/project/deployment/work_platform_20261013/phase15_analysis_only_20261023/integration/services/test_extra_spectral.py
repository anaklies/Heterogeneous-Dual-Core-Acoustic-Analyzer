"""Production scalar C execution; independent NumPy FFT syscall oracle only."""
import ctypes,json,subprocess,tempfile
from pathlib import Path
import numpy as np
from extra_spectral import *
HERE=Path(__file__).resolve().parent
DLL=Path(tempfile.mkdtemp(prefix='sixmic_extra_',dir=HERE.parents[4]/'tmp'))/'scalar.dll'
subprocess.run(['D:/mingw64/bin/g++.exe','-DSIXMIC_NATIVE','-std=c++17','-O2','-shared',str(HERE.parent/'shared_backend/scalar_engine.cpp'),'-o',str(DLL)],check=True)
fn=ctypes.CDLL(str(DLL)).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
mem=np.zeros(720000,np.float32); reports=[];rng=np.random.default_rng(3106)

def put(power):
    mem[262144+4098:262144+7171:3]=power

def run(s):
    requests=[]
    for chunks in range(1,60000):
        st=ctypes.c_uint();fn(mem.ctypes.data,s['descriptor'],len(mem),0,ctypes.byref(st));v=st.value
        assert not v&255,hex(v)
        if v&0x40000000:
            mode=(v>>28)&3;out=((v>>18)&1023)<<12
            assert mode in (1,2) and out==s['output']
            z=mem[out+4096:out+8192:2].astype(float)+1j*mem[out+4097:out+8192:2]
            z=np.fft.ifft(z) if mode==2 else np.fft.fft(z);mem[out+8192:out+12288:2]=z.real;mem[out+8193:out+12288:2]=z.imag;requests.append(mode)
        if v&0x80000000:break
    else:raise AssertionError('no completion')
    a=mem[s['output']:s['output']+s['metadata']['output_count']].copy()
    assert np.isfinite(a).all()
    return a,chunks,requests

def check(spec,gold,label=None,s=None):
    s=install(mem,spec) if s is None else s;a,chunks,requests=run(s)
    np.testing.assert_allclose(a,gold,rtol=2e-4,atol=4e-6)
    reports.append(dict(service=label or s['metadata']['service'],values=len(a),instructions=s['program_instructions'],chunks=chunks,fft_modes=requests,max_absolute_error=float(np.max(abs(a-gold)))))
    return s,a

p=rng.random(1025).astype(np.float32)*.02;put(p)
for f0 in (375,1010):
    spec=harmonic_energy(48000,f0,6);ranges=spec[1]['bin_ranges'];e=np.array([p[a:b].sum(dtype=float) for a,b in ranges]);gold=np.r_[e,np.sqrt(e[1:].sum()/e[0]),1]
    check(spec,gold)
spec=sidebands(48000,6000,375,30);e=np.array([p[a:b].sum(dtype=float) for a,b in spec[1]['bin_ranges']]);check(spec,np.r_[e,e[0]/e[1],e[2]/e[1],1])
put(np.zeros(1025));check(sidebands(48000,6000,375,30),np.zeros(6),'sideband_silence')
# Cumulative distinct frame history, silence first and bins exactly zero throughout.
spec=spectral_kurtosis(count=64);s=install(mem,spec);rows=[]
for frame in range(1,8):
    x=np.zeros(1025,np.float32) if frame==1 else rng.random(1025).astype(np.float32)*.1;x[:4]=0;put(x);rows.append(x[:64])
    arr=np.array(rows,dtype=float);s1=arr.sum(axis=0);s2=(arr*arr).sum(axis=0);M=frame
    kurt=(M+1)/max(M-1,1)*(M*s2/np.maximum(s1*s1,1e-20)-1)-1
    valid=((M>=3)&(s1>=1e-20)).astype(float);gold=np.r_[M,np.stack([s1,s2,kurt,valid],axis=1).ravel()]
    check(spec,gold,'kurtosis_frame_'+str(frame),s)
# Periodic tones/non-integer tone, random noise, silence. Integer lag quantization
# is independently evaluated against the exact circular reference, not hidden f0.
for label,f in [('tone',1000),('offbin',733),('noise',None),('silence',0)]:
    x=rng.normal(size=2048) if f is None else np.zeros(2048) if not f else np.sin(2*np.pi*f*np.arange(2048)/48000)
    x=(x-x.mean())*np.hanning(2049)[:-1];X=np.fft.fft(x)
    mem[262144:266240:2]=X.real;mem[262145:266240:2]=X.imag
    spec=periodicity(48000);lo,hi=spec[1]['lag_range'];r=np.fft.ifft(abs(X)**2).real;r=r/max(r[0],1e-20)
    k=lo+np.argmax(r[lo:hi+1]);best=r[k];valid=best>=.7;gold=[48000/k if valid else 0,best,1 if valid else 0]
    check(spec,gold,'periodicity_'+label)
# Explicit assembler bounds and no false ZoomFFT implementation claim.
for bad in (lambda:harmonic_energy(48000,100,half_width=60),lambda:sidebands(48000,6000,50,30),lambda:periodicity(48000,min_hz=3000,max_hz=2000)):
    try:bad();raise AssertionError('invalid configuration accepted')
    except ValueError:pass
# True Zoom: longer captured trace, frequency translation, FIR then decimation.
# Reference FIR from scipy.lfilter, independent of the microcoded loops.
from scipy.signal import lfilter
for D in (2,4):
    fs=48000;fc=12000 if D==2 else 11000;spec=zoom_spectrum(fs,fc,D);ss=install_zoom(mem,spec);m=ss['metadata'];L=m['raw_samples'];t=np.arange(L)/fs
    x=.3*np.cos(2*np.pi*(fc+937.5)*t)+.15*np.cos(2*np.pi*(fc-468.75)*t)+.1*np.cos(2*np.pi*1000*t)
    o=ss['output'];mem[o+m['raw_offset']:o+m['raw_offset']+L]=x
    z=x*np.exp(-2j*np.pi*fc*t);h=np.asarray(m['coefficients']);v=lfilter(h,[1],z)[len(h)-1::D][:2048]
    Y=np.fft.fft(v*np.hanning(2049)[:-1]);gold=np.stack([abs(Y)/1024,abs(Y)**2/(fs/D*768)],axis=1).ravel()
    a,chunks,requests=run(ss);np.testing.assert_allclose(a,gold,rtol=6e-3,atol=2e-5)
    reports.append(dict(service='true_zoom_D'+str(D),values=len(a),instructions=ss['program_instructions'],chunks=chunks,fft_modes=requests,max_absolute_error=float(np.max(abs(a-gold))),raw_samples=L,resolution_hz=m['resolution_hz'],private_output_bytes=65536*4))

result=dict(scope='Native production scalar C, independent NumPy arithmetic/FFT syscall golden; NOT RTL/physical acceptance',cases=reports,total_compared=sum(r['values'] for r in reports),
implemented=['selected harmonic integrated energy and THD','selected carrier sideband integrated power','cumulative per-bin spectral kurtosis with validity','bounded circular periodicity estimate','true heterodyne FIR-decimation Zoom FFT of captured longer record'],
unsupported=['Historical zero-padded linear autocorrelation fundamental estimator not ported exactly','Automatic order tracking without tachometer not claimed'],
caller_contract=['Fresh frameId exactly once for kurtosis; reset output state on configuration or sample-rate change','All chunk calls for one service retain pinned source slot','User selected f0/carrier/spacing are configuration, not hidden target truth','Validity must be consumed; no absolute SPL or equipment diagnosis'],
cost='All <=1024 instruction programs with <=64 instructions/chunk; kurtosis O(bins) per frame and 4*bins+1 history words; periodicity one shared 2048 IFFT plus O(2048+lagrange) scalar operations; Zoom 65tap FIR only at decimated positions + oscillator + one2048FFT, about25000chunks and256KiB DDR output area (not BRAM)' )
(HERE/'EXTRA_RESULTS.json').write_text(json.dumps(result,indent=2));print('EXTRA_SPECTRAL_NATIVE_PASS cases',len(reports),'values',result['total_compared'])


