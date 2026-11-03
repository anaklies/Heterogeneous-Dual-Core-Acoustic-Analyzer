"""Native PL VM program equivalence, not a board timing result."""
from pathlib import Path
import ctypes,json
import numpy as np
from cross_spectral_services import cross_spectra,install_cross
HERE=Path(__file__).resolve().parent
fn=ctypes.CDLL(str(HERE/'services_scalar.dll')).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
rng=np.random.default_rng(20261023);mem=np.zeros(700000,np.float32);results=[]
def run(spec,slot):
    for chunks in range(1,10000):
        status=ctypes.c_uint();fn(mem.ctypes.data,spec['descriptor']+slot*16,len(mem),slot,ctypes.byref(status))
        assert status.value&255==0,hex(status.value)
        if status.value&0x80000000:break
    else:raise AssertionError('no end')
    v=mem[spec['output']:spec['output']+spec['output_words']].copy();assert np.isfinite(v).all()
    return v,chunks

def put(slot,ch,x):
    o=262144+slot*65536+ch*8192
    mem[o:o+2050:2]=x.real;mem[o+1:o+2050:2]=x.imag

def case(name,frames,first=0,count=1025):
    spec=install_cross(mem,cross_spectra(first=first,count=count)); xx=yy=cr=ci=None
    maxerr=0;steps=0
    for frame,(x,y) in enumerate(frames):
        slot=frame%4;put(slot,0,x);put(slot,1,y);v,chunks=run(spec,slot);steps=max(steps,chunks)
        sl=slice(first,first+count);a=x[sl].astype(np.complex128);b=y[sl].astype(np.complex128)
        if xx is None:xx=np.zeros(count);yy=xx.copy();cr=xx.copy();ci=xx.copy()
        xx+=abs(a)**2;yy+=abs(b)**2;cross=np.conj(a)*b;cr+=cross.real;ci+=cross.imag
        scale=np.full(count,2/(48000*768*(frame+1)));bins=np.arange(first,first+count)
        scale[(bins==0)|(bins==1024)]*=.5
        valid=(frame>=1)&(xx>=1e-30)&(yy>=1e-30)
        coh=np.where(valid,(cr*cr+ci*ci)/np.maximum(xx*yy,1e-300),0)
        gold=np.stack([xx,yy,cr,ci,xx*scale,yy*scale,cr*scale,ci*scale,np.clip(coh,0,1),np.angle(cr+1j*ci),valid],axis=1)
        out=v[1:].reshape(count,11);assert v[0]==frame+1
        # Phase polynomial existing design has absolute worst error <1e-5 rad.
        # Float32 cross-product cancellation needs power-scaled, not relative
        # error against an almost-zero real/imag component. Eight epsilon per
        # accumulated snapshot bounds the two products and their sum.
        power=np.maximum(xx+yy,1e-35)
        tolerance=np.stack([power]*4+[power*scale]*4+[np.ones(count)],axis=1)*np.finfo(np.float32).eps*8*(frame+1)
        assert np.all(np.abs(out[:,:9]-gold[:,:9]) <= tolerance), np.max(np.abs(out[:,:9]-gold[:,:9])/tolerance)
        np.testing.assert_allclose(out[:,10],gold[:,10],atol=0)
        phaseerr=np.abs(np.angle(np.exp(1j*(out[:,9]-gold[:,9]))))
        assert phaseerr.max()<1e-5,phaseerr.max()
        maxerr=max(maxerr,float(phaseerr.max()))
    results.append(dict(name=name,frames=len(frames),bins=count,compared=len(frames)*(1+11*count),maximum_chunks_per_frame=steps,max_phase_error_rad=maxerr))
    return out

z=lambda:(rng.normal(size=1025)+1j*rng.normal(size=1025)).astype(np.complex64)
case('random_independent_four_snapshots',[(z(),z()) for _ in range(4)])
frames=[]
for n in range(3):
    x=z();frames.append((x,x*np.complex64(np.exp(1j*.72))))
case('unity_coherence_positive_phase',frames)
frames=[]
for n in range(3):
    x=z();frames.append((x,x*np.complex64(np.exp(-1j*2.1))))
case('unity_coherence_negative_phase',frames,first=400,count=256)
case('weak_unity_coherence',[(np.ones(1025,np.complex64)*1e-10,np.ones(1025,np.complex64)*1e-10)]*2)
case('silence_two_frames',[(np.zeros(1025,np.complex64),np.zeros(1025,np.complex64))]*2)
# Explicit cardinal quadrants incl DC/Nyquist; valid after 2 frames.
x=np.ones(1025,np.complex64);y=np.resize(np.array([1,1j,-1,-1j],np.complex64),1025)
case('quadrant_and_endpoint_normalization',[(x,y)]*2)
# Actual independent time blocks and SciPy Welch/CSD convention + density.
from scipy.signal import csd,welch,get_window
xt=rng.normal(size=6144).astype(np.float32)
yt=(.5*np.roll(xt,3)+rng.normal(size=6144)*.2).astype(np.float32)
w=get_window('hann',2048).astype(np.float32)
frames=[(np.fft.rfft(xt[j:j+2048]*w).astype(np.complex64),np.fft.rfft(yt[j:j+2048]*w).astype(np.complex64)) for j in range(0,6144,2048)]
out=case('scipy_csd_welch_three_time_blocks',frames)
kw=dict(fs=48000,window='hann',nperseg=2048,noverlap=0,detrend=False,scaling='density')
_,px=welch(xt,**kw);_,py=welch(yt,**kw);_,pc=csd(xt,yt,**kw)
np.testing.assert_allclose(out[:,4:8],np.stack([px,py,pc.real,pc.imag],axis=1),rtol=2e-4,atol=2e-10)

result=dict(verification='Native shared PL scalar C versus independent NumPy definitions, no RTL or hardware throughput claim',
 cases=results,total_compared=sum(v['compared'] for v in results),
 limitations=['Caller must reject duplicate frameId before dispatch; snapshot pin alone does not establish freshness.',
 'Caller must select sufficiently independent windows for statistical coherence. Count >=2 alone is necessary, not sufficient.',
 'Partial/error results invalid until complete fence; reset history on session/pair/config changes.',
 'No absolute SPL; raw 2048 Hann FFT assumes window energy 768; normalization must match selected FFT mode.',
 'Selected pair only; does not claim all 15 simultaneous pairs or 10 Hz full spectral service.'],
 costs={'full_bins_output_history_bytes':(1+11*1025)*4,'bytecode_bytes':cross_spectra()[0].words.__len__()*16,'max_vm_steps_per_bin_upper_bound':140,'private_allocation_bytes':24576*4})
(HERE/'CROSS_RESULTS.json').write_text(json.dumps(result,indent=2))
print('CROSS_SPECTRAL_NATIVE_PASS',result['total_compared'])
