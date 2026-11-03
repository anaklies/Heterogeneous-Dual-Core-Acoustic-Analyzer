"""Emit deterministic DDR initialization records; no run-time signal processing."""
from pathlib import Path
import hashlib,json
import numpy as np
from programs import install,vector,smoothing,band_sums,shape,difference
from frequency_drift import frequency_drift
from analysis_statistics import welch

HERE=Path(__file__).resolve().parent
BASE=600000
STRIDE=24576
def build(sample_rate=49162010/1024,session=1,config=1,generation=1):
    if any(not isinstance(x,int) or not 1<=x<=0xffffffff for x in (session,config,generation)):
        raise ValueError("uint32 nonzero identities required")
    definitions=[('snapshot',vector('copy')),('peak_hold',vector('peak_hold')),
        ('spectrum_ema',vector('ema')),('smoothing',smoothing()),
        ('octave',band_sums(sample_rate,1)),('third_octave',band_sums(sample_rate,3)),
        ('shape',shape(sample_rate)),('flux_delta',difference()),
        ('welch',welch()),('frequency_drift',frequency_drift(sample_rate))]
    memory=np.zeros(BASE+STRIDE*len(definitions),np.float32)
    specs={name:install(memory,program,BASE+i*STRIDE,session=session,config=config,generation=generation) for i,(name,program) in enumerate(definitions)}
    image=memory[BASE:].view(np.uint32).astype('<u4').tobytes()
    (HERE/'service_bundle.bin').write_bytes(image)
    info=dict(format='LE32 raw words; bit-preserving float/integer ABI',
        word_offset=BASE,byte_offset=BASE*4,byte_length=len(image),sample_rate=sample_rate,
        sha256=hashlib.sha256(image).hexdigest(),services=specs,session=session,config=config,generation=generation,
        p1_carousel=dict(base=BASE,last_index=len(definitions)-1,stride_words=STRIDE),
        installation='Load only with scalar idle; configure P1 base/last_index/stride from p1_carousel; every frame is pinned and source metadata comes from hardware. Outputs published only after final DONE and AXI completion fence.')
    (HERE/'service_bundle.json').write_text(json.dumps(info,indent=2))
    return info
if __name__=='__main__':
    result=build();print('SERVICE_BUNDLE_WRITTEN bytes=',result['byte_length'])
