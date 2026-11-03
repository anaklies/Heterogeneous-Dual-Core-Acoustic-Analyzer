"""One finite batch. Newtransmission mechanisms plusread-onlydailyIR references."""
from pathlib import Path
import json,time,hashlib
import numpy as np
from scipy import signal
import soundfile as sf
from algorithms.stipa_experimental import generate_reference,measure,FS
from algorithms.room_ir import reverberation_time,clarity
P=Path(__file__).resolve().parent;M=P.parent/'phase12m_product_algorithm_acceptance_20261021'


def plain(v):
    if isinstance(v,np.ndarray):return plain(v.tolist())
    if isinstance(v,np.generic):return plain(v.item())
    if isinstance(v,float) and not np.isfinite(v):return None
    if isinstance(v,dict):return {k:plain(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [plain(x) for x in v]
    return v


def main():
    out=P/'results';out.mkdir(exist_ok=True)
    assert not (out/'quick_validation.json').exists(),'Preserve first locked-rule batch, no repeated retuning'
    start=time.perf_counter();x,meta=generate_reference(20)
    examples=P/'examples';examples.mkdir(exist_ok=True)
    sf.write(examples/'STIPA_research_reference.wav',x,FS,subtype='PCM_24')
    (examples/'STIPA_research_reference.json').write_text(json.dumps(meta,indent=2))
    rng=np.random.default_rng(14211053);rows=[]
    variants=[('reference_loopback',x),('gain_only',x*.5)]
    noise=rng.normal(size=len(x));noise/=np.sqrt(np.mean(noise*noise))
    for snr in [20,10]:variants.append((f'noise_{snr}dB',x+noise*np.sqrt(np.mean(x*x)/10**(snr/10))))
    for rt,drr in [(.3,6),(.5,0)]:
        t=np.arange(round(.8*FS))/FS
        h=rng.normal(size=len(t))*np.exp(-6.907755*t/rt)
        h[:round(.008*FS)]=0;h*=np.sqrt(10**(-drr/10)/np.sum(h*h));h[0]=1
        y=signal.fftconvolve(x,h)[:len(x)]
        variants.append((f'reflection_proxy_rt{rt}_drr{drr}',y))
    for name,y in variants:
        began=time.perf_counter();r=measure(y,x,test_signal_confirmed=True)
        rows.append(dict(id=name,result=r,CPUSeconds=time.perf_counter()-began,
                         inputSHA256=hashlib.sha256(y.astype('<f8').tobytes()).hexdigest()))
        print('STIPA_QUICK',name,r['valid'],r.get('estimate'),flush=True)
    assert rows[0]['result']['valid'] and abs(rows[0]['result']['estimate']-1)<1e-8
    assert rows[1]['result']['valid'] and abs(rows[1]['result']['estimate']-1)<1e-8
    # A mechanism check, not a selected threshold or roomacceptanceclaim.
    assert rows[3]['result']['estimate']<rows[0]['result']['estimate']
    rooms=[]
    for i in range(3):
        source=M/f'data/rir/Mroom{i}_0.npz'
        h=np.load(source)['full'][0]
        rr=reverberation_time(h,FS);cc=clarity(h,FS)
        # Don't archive fullfloatingcurves again; inputs remainhashreferenced.
        keep={k:v for k,v in rr.items() if k not in {'decay','curve','decayCurve'}}
        rooms.append(dict(id=f'reused_Mroom{i}',source=str(source),inputSHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
                          reverberation=keep,clarity=cc))
    result=dict(stipa=rows,reusedDailyRoomIR=rooms,CPUSeconds=time.perf_counter()-start,
        independentNewRooms=0,realHardware=False,ordinaryRoomUniversalPass=False,
        calibration='relative/experimental, not acoustic certification',rulesRetuned=False)
    (out/'quick_validation.json').write_text(json.dumps(plain(result),ensure_ascii=False,indent=2),encoding='utf-8')
    print('QUICK_VALIDATION_SAVED',time.perf_counter()-start,flush=True)


if __name__=='__main__':main()
