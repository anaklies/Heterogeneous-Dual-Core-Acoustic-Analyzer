"""Affected coarse dot quantization only; inherit previous decoder accuracy tests."""
from pathlib import Path
import ctypes,json,sys
import numpy as np
P=Path(__file__).resolve().parents[1]
D=P/'pl_system/doa'
bank=np.fromfile(P/'examples/doa_bank_q14.bin','<i2')
def load(name):
    f=getattr(ctypes.CDLL(str(D/(name+'.dll'))),name)
    f.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_float,ctypes.c_float,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
    def run(v):
        v=np.ascontiguousarray(v,dtype=np.float32);o=np.zeros(9,np.float32)
        f(v.ctypes.data,bank.ctypes.data,343.,.1,1,1,o.ctypes.data)
        return o
    return run
variant=sys.argv[1] if len(sys.argv)>1 else 'q'
assert variant in ('q','shared')
old,new=load('doa_first'),load('doa_first_'+variant)
rows=[]
vectors=[]
for name,path in [('saved_window',P/'pl_system/nn_window/window_output.bin'),
                  ('fixed_fft_window',P/'results/fixed_frontend_window.bin')]:
    raw=path.read_bytes()
    vectors.append((name,np.frombuffer(raw[76576*2:76576*2+1890*4],'<f4')))
for index in [0,292,613]:
    vectors.append((f'coarse_point_{index}',bank.reshape(614,1890)[index].astype(np.float32)/16384))
for name,v in vectors:
    a,b=old(v),new(v)
    angle=float(np.degrees(np.arccos(np.clip(np.dot(a[2:5],b[2:5])/
               np.linalg.norm(a[2:5])/np.linalg.norm(b[2:5]),-1,1))))
    assert a[0]==b[0] and angle<1 and abs(a[1]-b[1])<2e-5,(name,a,b)
    assert abs(a[7]-b[7])<2e-5
    rows.append(dict(id=name,directionChangeDegrees=angle,
        finalScoreChange=float(abs(a[1]-b[1])),coarseScoreChange=float(abs(a[7]-b[7]))))
assert new(np.zeros(1890))[0]==0
if variant=='q':
    assert new(np.full(1890,257.))[0]==0
assert new(np.full(1890,np.nan))[0]==0
result=dict(status='PASS_AFFECTED_C_MODEL',variant=variant,rows=rows,
    format='signed32Q20 coarse dot' if variant=='q' else 'unchanged float arithmetic; shared wave/angle hardware',
    mathematicalAbsoluteScoreQuantizationBound=1/1048576 if variant=='q' else 0,
    coarsePointCount=614,componentsPerPoint=1890,fullRTL=False)
(P/f'tests/decoder_{variant}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('DECODER_PASS',variant,len(rows),'paired cases; silence/NaN rejected')
