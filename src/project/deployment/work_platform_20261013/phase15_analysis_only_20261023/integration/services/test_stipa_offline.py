from pathlib import Path
import ctypes, json, sys, time
import numpy as np
from scipy import signal
from stipa_offline import *
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'phase14_room_and_pl_20261021'/'algorithms'))
from stipa_experimental import modulation_depth
fn=ctypes.CDLL(str(HERE/'services_scalar.dll')).scalar_native
fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
checks=[]; memory=np.zeros(800000,np.float32); gen=0

def run(c,q):
    global gen
    gen+=1;spec=install_stage(memory,c,q,generation=gen);status=ctypes.c_uint();chunks=0
    while True:
        fn(memory.ctypes.data,spec['descriptor'],len(memory),0,ctypes.byref(status));chunks+=1
        assert not status.value&255,hex(status.value)
        if status.value&0x80000000:break
        assert chunks<300000
    return spec['output'],chunks

rng=np.random.default_rng(8127)
# Every one of the7 exact SOS topologies; short traces validate filtering but
# are deliberately invalid for STIPA duration.
n=257;q=layout(n);out=524288+8192
for band in range(7):
    x=rng.normal(0,.03,n).astype(np.float32);memory[out:out+n]=x
    c,q,sections=filter_program(n,band,0);off,k=run(c,q)
    # Compare quantized SOS using independent SciPy, not reimplementing VM.
    y=signal.sosfilt(sections[:9].astype(np.float32),x)
    expected=signal.sosfilt(sections[9:].astype(np.float32),y*y)
    actual=memory[off+2*n:off+3*n]
    np.testing.assert_allclose(actual,expected,rtol=.005,atol=2e-8)
    checks.append(dict(name=f'band{band}_11SOS',values=n,chunks=k,maxAbs=float(np.max(abs(actual-expected))),instructions=len(c.words)))
# Verify exact static transpose of frozen decimator+LS with a finite record.
n=33600;q=layout(n);out=524288+8192;t=np.arange(n)/FS
intensity=(.1+.03*np.sin(2*np.pi*1.6*t)+.02*np.cos(2*np.pi*8*t)).astype(np.float32)
memory[out+2*n:out+3*n]=intensity
ref=signal.resample_poly(intensity.astype(float),1,240)[60:-60]
t200=np.arange(len(ref))/200
X=np.column_stack([np.ones(len(ref)),t200-t200.mean(),*[v for f in PAIRS[0] for v in (np.sin(2*np.pi*f*t200),np.cos(2*np.pi*f*t200))]])
expected=np.linalg.lstsq(X,ref,rcond=None)[0];coeff=[]
for j in range(6):
    w=regression_weights(n,0,j);memory[out+3*n:out+4*n]=w
    # Adjoint identity independent of VM float32 roundoff.
    np.testing.assert_allclose(np.dot(w.astype(float),intensity),expected[j],rtol=2e-4,atol=1e-6)
    c,q=fit_program(n,0,0,j);off,k=run(c,q);coeff.append(float(memory[off+q['result']+48+j]))
    checks.append(dict(name=f'exact_decimator_LS_coefficient{j}',values=1,chunks=k,maxAbs=abs(coeff[-1]-expected[j]),instructions=len(c.words)))
np.testing.assert_allclose(coeff,expected,rtol=.02,atol=.0003)
for confirm in [False,True]:
    c,q=mtf_program(n,confirm);off,k=run(c,q);assert memory[off+q['result']]==0
    checks.append(dict(name='short_record_invalid_'+str(confirm),values=1,chunks=k,instructions=len(c.words)))
# Check full duration validation/ratios with synthetic PL sufficient statistics,
# explicitly not a15s full waveform Native claim.
n=720000;q=layout(n);memory=np.zeros(524288+8192+q['words'],np.float32);out=524288+8192
for b in range(7):
    for tr in (0,1):
        memory[out+q['result']+32+2*b+tr]=.1
        a=out+q['result']+48+tr*42+b*6
        memory[a:a+6]=[.1,0,.04*(1 if tr==0 else .6),0,.03*(1 if tr==0 else .6),0]
memory[out:out+2*n]=.01
c,q=validation_program(n,True);off,k=run(c,q);assert memory[out+q['result']+31]==1
checks.append(dict(name='full15sec_PL_capture_scan',values=2*n,chunks=k,instructions=len(c.words)))
memory[out+n//2]=1;c,q=validation_program(n,True);off,k=run(c,q);assert memory[out+q['result']+31]==0
checks.append(dict(name='clipped_capture_rejected',values=1,chunks=k,instructions=len(c.words)))
memory[out+n//2]=.01;c,q=validation_program(n,True);off,k=run(c,q);assert memory[out+q['result']+31]==1
c,q=mtf_program(n,True);off,k=run(c,q);assert memory[off+q['result']]==1
np.testing.assert_allclose(memory[off+q['result']+2:off+q['result']+16],.6,atol=1e-6)
checks.append(dict(name='14_MTF_ratio_validation',values=15,chunks=k,instructions=len(c.words)))
memory[out+q['result']+48+2]=.001;c,q=mtf_program(n,True);off,k=run(c,q);assert memory[off+q['result']]==0
report=dict(status='NATIVE_STAGE_TESTS_PASS_NOT_AUTONOMOUS_OR_REALTIME',checks=checks,
    exact_frozen_definition='9 SOS octave + square +2 SOS40Hz + scipy4801tap240decimator +trim60 +joint6LS',
    host_signal_DSP=False,host_configuration='SOS and six adjoint regression weight pages; no measured data used in coefficient construction',
    input='two normalized mono captured traces, reference and observation, staged in private DDR',
    stages='perband/trace11SOS pass then six regression dot passes, finally14MTF validator and existing PL combiner',
    orchestration='PS/PC uploads coefficient pages and submits completed jobs; not autonomous whole-chain PL yet',
    max_supported_seconds=(4194304-524288-8192-256)//4/48000,
    estimated_15sec_instructions=14*720000*(11*15+12+6*13),
    estimated_15sec_min_chunks=math.ceil(14*720000*(11*15+12+6*13)/64),
    limitations=['No15secondfull waveform Native test; stage tests only','Notlive; async P2 only; P0 maycontinue between bounded64instructionchunks','NoIEC certification or calibrated masking','PL clip/finite scan and metadata confirmation precede recipe; controller integration pending','Single selected microphone; no source separation','19s limit from4Mwordarena;60s requires future capture replay'],
    fpga='Shared scalar arithmetic; no additional synthesized resource claim; massive DDR/config paging traffic')
(HERE/'STIPA_OFFLINE_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(dict(status=report['status'],checks=len(checks),minChunks15s=report['estimated_15sec_min_chunks'])))


