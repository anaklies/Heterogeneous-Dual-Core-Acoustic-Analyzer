import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'algorithms'))
import numpy as np
import pytest
from room_ir import reverberation_time,clarity,octave_room_metrics,spectral_decay

FS=48000


def exponential_ir(rt,seconds=1.5):
    t=np.arange(int(seconds*FS))/FS
    # Dense deterministic alternating excitation with exact exponentialenergy.
    return np.exp(-3*np.log(10)*t/rt)*np.where(np.arange(len(t))%2,1.,-1.)


@pytest.mark.parametrize('rt',[.2,.4,.6])
def test_known_rt(rt):
    x=exponential_ir(rt)
    result=reverberation_time(x,onset_sample=0)
    assert result['valid']
    for key in ['EDT','T20','T30']:
        fit=result['fits'][key]
        assert fit['valid'] and abs(fit['estimateSeconds']-rt)<.003
        assert fit['fitR2']>.999


def test_gain_invariance():
    x=exponential_ir(.4)
    a=reverberation_time(x,onset_sample=0);b=reverberation_time(x*.003,onset_sample=0)
    assert abs(a['rt60Seconds']-b['rt60Seconds'])<1e-9
    ca,cb=clarity(x,onset_sample=0),clarity(x*.003,onset_sample=0)
    for key in ['C50DB','C80DB','D50Percent','centerTimeSeconds']:
        assert abs(ca[key]-cb[key])<1e-9


def test_high_noise_and_short_ir_rejected():
    rng=np.random.default_rng(101)
    x=exponential_ir(.4)+rng.normal(0,.15,int(1.5*FS))
    r=reverberation_time(x,onset_sample=0)
    assert not r['fits']['T20']['valid'] and not r['fits']['T30']['valid']
    assert not clarity(x,onset_sample=0)['valid']
    short=reverberation_time(exponential_ir(2,seconds=.05),onset_sample=0)
    assert not short['fits']['T30']['valid']


def test_noise_tail_limited_t30_without_fake_pass():
    rng=np.random.default_rng(61)
    x=exponential_ir(.5)+rng.normal(0,.02,int(1.5*FS))
    r=reverberation_time(x,onset_sample=0)
    assert r['curve']['stationaryTailDetected']
    assert not r['fits']['T30']['valid']


def test_clarity_reflection_at_known_delay():
    x=np.zeros(FS//2);x[0]=1;x[int(.06*FS)]=1
    r=clarity(x,onset_sample=0)
    assert abs(r['C50DB'])<1e-9 and r['D50Percent']==50
    assert r['infiniteClarity80'] and r['C80DB'] is None
    assert abs(r['centerTimeSeconds']-.03)<1e-12


def test_silent_and_impulse_not_fake_rt():
    assert not reverberation_time(np.zeros(4096))['valid']
    x=np.zeros(48000);x[0]=1
    assert not reverberation_time(x,onset_sample=0)['valid']


def test_bands_guard_and_decay_output():
    rng=np.random.default_rng(212)
    x=exponential_ir(.4)*rng.normal(size=int(1.5*FS))
    bands=octave_room_metrics(x,centers=[2,500,1000,23000])
    assert not bands[0]['valid'] and not bands[-1]['valid']
    assert bands[1]['reverberation']['fits']['T20']['valid']
    d=spectral_decay(x)
    assert d['valid'] and np.isfinite(d['relativePowerDB']).all()
    assert d['relativePowerDB'].shape==d['cumulativeBandDecayDB'].shape
    assert np.max(np.diff(d['cumulativeBandDecayDB'],axis=1))<1e-10


def test_channel_selection_and_invalid_input():
    x=exponential_ir(.3)
    a=reverberation_time(np.column_stack([np.zeros_like(x),x]),channel=1,onset_sample=0)
    assert abs(a['rt60Seconds']-.3)<.003
    with pytest.raises(ValueError):reverberation_time([float('nan')]*100)
    with pytest.raises(ValueError):octave_room_metrics(x,fraction=2)


def save_mechanism_examples():
    """Six finiteIR checks; intentionally not claimed as room generalization."""
    import json,time,hashlib
    rng=np.random.default_rng(14211021);rows=[]
    for label,rt,delay in [('small_room_IR',.25,.012),('office_IR',.4,.024),('classroom_IR',.6,.041)]:
        t=np.arange(int(1.5*FS))/FS
        ir=.12*rng.normal(size=len(t))*np.exp(-3*np.log(10)*t/rt)
        ir[0]+=1;ir[round(delay*FS)]+=.5
        for snr in [45,25]:
            noise_rms=np.sqrt(np.mean(ir[:2400]**2))/10**(snr/20)
            x=ir+rng.normal(0,noise_rms,len(ir))
            begin=time.perf_counter()
            r=reverberation_time(x,onset_sample=0,include_curve=False)
            c=clarity(x,onset_sample=0);d=spectral_decay(x)
            rows.append(dict(id=label,nominalLateDecaySeconds=rt,earlyReflectionDelaySeconds=delay,
                 earlyReferenceToNoiseDB=snr,rt=r,clarity=c,
                 decayCandidateCount=len(d.get('persistentSpectralCandidates',[])),
                 CPUSeconds=time.perf_counter()-begin,inputSHA256Float64LE=hashlib.sha256(x.astype('<f8').tobytes()).hexdigest()))
    module=Path(__file__).resolve().parents[1]/'algorithms/room_ir.py'
    result=dict(scope='six small syntheticIR mechanism checks; not new physically modeled rooms or hardware validation',seed=14211021,records=rows,
                sourceSHA256=hashlib.sha256(module.read_bytes()).hexdigest(),
                testAndReproductionSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (Path(__file__).parent/'room_results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print('ROOM_IR_MECHANISM_EXAMPLES6_COMPLETE')


if __name__=='__main__':
    save_mechanism_examples()
