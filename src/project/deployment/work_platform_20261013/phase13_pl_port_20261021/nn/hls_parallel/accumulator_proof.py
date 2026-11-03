"""Conservative full-int16-domain proof for the new48-bit affine accumulators."""
from pathlib import Path
import json,math
import numpy as np
P=Path(__file__).resolve().parent
manifest=json.loads((P.parent/'tensor_manifest.json').read_text());data=np.fromfile(P.parent/'weights_i16.bin','<i2')
items={t['name']:t for t in manifest['tensors']}
def values(name):
    t=items[name];return data[t['offsetWords16']:t['offsetWords16']+t['elements']].reshape(t['shape']).astype(np.int64)
def align(x,shift):
    if shift>=0:return x<<shift
    k=-shift
    return np.where(x>=0,(x+(1<<(k-1)))>>k,-((-x+(1<<(k-1)))>>k))
rows=[]
for name,inputfrac in [('conv',11),('depth',10),('point',10),('embed',10),('gru_ih',10),('gru_hh',14),('phase',14),('support',14)]:
    weight,bias=(('gru.weight_ih_l0','gru.bias_ih_l0') if name=='gru_ih' else
                 ('gru.weight_hh_l0','gru.bias_hh_l0') if name=='gru_hh' else (name+'.weight',name+'.bias'))
    w=values(weight).reshape(items[weight]['shape'][0],-1);b=values(bias)
    frac=inputfrac+items[weight]['fractionalExponent'];bs=items[bias]['fractionalExponent']
    bound=np.abs(align(b,frac-bs))+32768*np.sum(np.abs(w),axis=1)
    maximum=int(bound.max());assert maximum<(1<<47)
    rows.append(dict(layer=name,inputFraction=inputfrac,productFraction=frac,biasFraction=bs,
                     conservativeMaximumAbsoluteAccumulator=maximum,signedBitsNeeded=maximum.bit_length()+1,
                     proof='abs(alignedBias)+32768*sum(abs(actualQuantizedWeights)); all possible signed16 activations'))
(P/'ACCUMULATOR_PROOF.json').write_text(json.dumps(dict(status='PASS',rows=rows,
    hardwareAccumulatorBits=48,doesNotProveTiming=True,doesNotIncludeUnimplementedFrontend=True),indent=2))
print('ACCUMULATOR48_FULLDOMAIN_PROOF_PASS',max(r['signedBitsNeeded'] for r in rows),'bits needed')
