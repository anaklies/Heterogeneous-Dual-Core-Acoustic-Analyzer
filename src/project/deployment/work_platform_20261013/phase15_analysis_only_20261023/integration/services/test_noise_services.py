"""Independent scalar Native comparison; no RTL or physical acoustic claim."""
from pathlib import Path
import ctypes,json,sys
import numpy as np
from scipy.signal import lfilter
from noise_services import *

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'phase14_room_and_pl_20261021'/'algorithms'))
from noise_metrics import analog_weighting_db,nr_curves,nc_curves,noise_curve_rating
from stipa_experimental import combine_mtf
fn=ctypes.CDLL(str(HERE/'services_scalar.dll')).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
memory=np.zeros(700000,np.float32); reports=[]
def run(spec):
    for chunk in range(10000):
        status=ctypes.c_uint()
        fn(memory.ctypes.data,spec['descriptor'],len(memory),0,ctypes.byref(status))
        assert not status.value&255,hex(status.value)
        if status.value&0x80000000: break
    else: raise AssertionError('timeout')
    actual=memory[spec['output']:spec['output']+spec['output_words']].copy()
    assert np.isfinite(actual).all()
    return actual,chunk+1
def compare(name,a,b,chunks,rtol=5e-5,atol=1e-7):
    np.testing.assert_allclose(a,b,rtol=rtol,atol=atol)
    reports.append(dict(name=name,values=int(np.size(b)),chunks=chunks,max_abs_error=float(np.max(np.abs(a-b)))))
rng=np.random.default_rng(911); fs=49162010/1024
psd=rng.random(1025).astype(np.float32)*1e-7
memory[262144+4097:262144+7171:3]=psd
for mode in ['A','C','Z']:
    spec=install_noise(memory,weighted_level(fs,mode)); a,k=run(spec)
    gain=10**(analog_weighting_db(np.arange(1025)*fs/2048,mode)/10)
    p=np.dot(psd.astype(float),gain)*fs/2048
    compare(mode,a[:3],[p,10*np.log10(p),1],k)
memory[262144+4097:262144+7171:3]=0
spec=install_noise(memory,weighted_level(fs));a,k=run(spec);compare('silent_weighting',a[:3],[0,-200,0],k)

pcm=rng.integers(-1000000,1000000,2048,dtype=np.int32)
memory.view(np.int32)[:2048]=pcm
x=pcm.astype(float)/8388608
for mode,tau in [('FAST',.125),('SLOW',1)]:
    spec=install_noise(memory,time_response(fs,mode));a,k=run(spec)
    alpha=np.float32(np.exp(-1/(fs*tau)));beta=np.float32(1-np.exp(-1/(fs*tau)))
    y=lfilter([beta],[1,-float(alpha)],x*x)
    compare(mode,a[:4],[y[-1],10*np.log10(y[-1]),2048,np.mean(x*x)],k,rtol=8e-5)
    a,k=run(spec)
    yy=lfilter([beta],[1,-float(alpha)],np.tile(x*x,2))
    compare(mode+'_resume',a[[0,2,5]],[yy[-1],4096,10*np.log10(np.mean(x*x))],k,rtol=8e-5)
    assert a[7]==1
    memory[spec['output']+2]=2048*8388608
    a,k=run(spec); assert a[7]==0
    reports.append(dict(name=mode+'_counter_bound',values=1,chunks=k,max_abs_error=0))

spec=install_noise(memory,level_statistics()); observations=[]
for i in range(18):
    rms=np.float32(.001+(i%9)*.002); memory[262144+7171]=rms
    observations.append(20*np.log10(float(rms)))
    a,k=run(spec)
    assert a[4]==int(i>=15)
    if i>=15:
        last=np.array(observations[-16:]); q=np.percentile(last,[90,50,10]); leq=10*np.log10(np.mean(10**(last/10)))
        compare('rolling_level_statistics',a[:6],np.r_[q,leq,1,16],k)

for metadata in [False,True]:
    spec=install_noise(memory,relative_band_difference(9,metadata));out=spec['output']
    p=np.linspace(.001,.009,9);q=p/4
    memory[out+18:out+27]=p;memory[out+27:out+36]=q
    a,k=run(spec);compare('relative_insulation_'+str(metadata),a[:18],np.r_[np.full(9,10*np.log10(4) if metadata else 0),np.full(9,int(metadata))],k)
spec=install_noise(memory,relative_band_difference(2,True));out=spec['output'];memory[out+4:out+8]=[0,.1,.1,0]
a,k=run(spec);compare('insufficient_band_power',a[:4],[0,0,0,0],k)

for ratios in [np.full((7,2),.2),np.full((7,2),.8),rng.uniform(.05,1,(7,2))]:
    spec=install_noise(memory,stipa_combine(True));out=spec['output'];memory[out+16:out+30]=ratios.ravel()
    a,k=run(spec);compare('mtf_combine',a[:3],[combine_mtf(ratios)['estimate'],1,0],k)
for value in [-.1,1.4]:
    spec=install_noise(memory,stipa_combine(True));out=spec['output'];memory[out+16:out+30]=.5;memory[out+16]=value
    a,k=run(spec);compare('bad_mtf_rejected',a[:3],[0,0,0],k)
spec=install_noise(memory,stipa_combine(False));a,k=run(spec);compare('unconfirmed_stipa',a[:3],[0,0,0],k)
for family,curves in [('NR',nr_curves()),('NC',nc_curves())]:
    for mode in [None,'nominal','calibrated']:
        calibration=None if mode is None else dict(mode=mode,offsetDB=105,source='explicit test reference')
        for row in [0,len(curves['ratings'])//2,len(curves['ratings'])-1]:
            levels=(curves['levelsDBSPL'][row]-.25-105).astype(np.float32)
            spec=install_noise(memory,noise_curve(family,calibration));out=spec['output']
            memory[out+32:out+32+len(levels)]=levels
            a,k=run(spec)
            gold=noise_curve_rating(levels,family=family,calibration=calibration)
            compare(family+'_'+str(mode),a[:3],[gold['rating'] or 0,int(gold['valid']),int(mode=='nominal') if gold['valid'] else 0],k)
    calibration=dict(mode='calibrated',offsetDB=0,source='explicit test reference')
    spec=install_noise(memory,noise_curve(family,calibration,'dBSPL'));out=spec['output']
    memory[out+32:out+32+len(curves['centerHz'])]=200
    a,k=run(spec);compare(family+'_above_table',a[:3],[0,0,0],k)
result=dict(evidence='PL scalar Native C interpreter versus NumPy/SciPy and frozen formula reference; no RTL/hardware timing',
    cases=reports,total_values=sum(x['values'] for x in reports),
    unsupported=['NC/NR valid rating requires explicit calibrated/nominal SPL reference and resolved octave band input',
    'L10/L50/L90 uses 16 uniform observations only, not arbitrarily long history',
    'full STIPA acquisition, octave filters, envelope extraction and modulation regression not implemented; only final MTF combiner',
    'spectral A/C not equivalent to IEC time-domain filters; FAST/SLOW here Z only',
    'relative insulation needs PL band producer, two captures and matching operator metadata; not Rw/DnT',
    'time-response descriptor must consume each hop once; gap reset and session sample count cap required'],
    stipa_frontend_cost=dict(frozen_bandpass_sos=7*9,frozen_intensity_lowpass_sos=7*2,
        total_sos_per_sample=77,minimum_multiply_per_second_one_capture=77*5*48000,
        reference_plus_observation_minimum_multiply=77*5*48000*2,
        shared_scalar_minimum_instructions_per_second_one_capture=77*9*48000,
        scalar_clock_hz=50000000,
        conclusion='Even ignoring loads/stores/checkpoints, >=33.264M scalar arithmetic instructions/s for one capture. Shared multi-cycle floating operations plus DDR state exceed credible real-time budget. No live full-STIPA claim; only final combiner tested. Captured/offline all-PL frontend needs separate sequencing and numerical regression; not implemented in this bounded addendum.'))
(HERE/'NOISE_RESULTS.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('NOISE_NATIVE_PASS',len(reports),result['total_values'])
