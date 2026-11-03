from pathlib import Path
import sys,ctypes,subprocess,json,hashlib
import numpy as np
sys.dont_write_bytecode=True
P=Path(__file__).resolve().parents[1];M=P.parent/'phase12m_product_algorithm_acceptance_20261021'
sys.path.insert(0,str(M));import mcontext
from model_j import pair_features
from features import stft
H=P/'hls'
subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-shared',str(H/'neural_features.cpp'),'-o',str(H/'neural_features.dll')],check=True)
fn=ctypes.CDLL(str(H/'neural_features.dll')).neural_features
fn.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
rows=[]
for name in ['Mroom0_0','Mroom0_1','Mroom1_0','Mroom1_1']:
    source=M/f'data/cases/{name}.npz';pcm=np.load(source)['pcm'][-11776:]
    X=stft(pcm);packed=np.ascontiguousarray(np.stack([X.real,X.imag],-1),dtype=np.float32)
    expected=np.clip(np.rint(pair_features(X)*2048),-32768,32767).astype(np.int16)
    output=np.zeros(expected.shape,np.int16);sat=ctypes.c_uint(0)
    fn(packed.ctypes.data,output.ctypes.data,ctypes.byref(sat))
    difference=abs(output.astype(int)-expected.astype(int))
    assert sat.value==0 and difference.max()<=1,(name,difference.max(),sat.value)
    rows.append(dict(id=name,elements=int(output.size),maximumDifferenceLSB=int(difference.max()),
        differingElements=int((difference!=0).sum()),saturations=sat.value,
        inputSHA256=hashlib.sha256(packed.tobytes()).hexdigest(),fixedFormat='signed16Q11',fullRTL=False))
(P/'tests/neural_features.json').write_text(json.dumps(dict(rows=rows,totalElements=sum(r['elements'] for r in rows),status='PASS_Q11_TOLERANCE_1LSB'),indent=2))
print('NEURAL_FEATURES_C_PASS',sum(r['elements'] for r in rows),'elements,1LSB maximum')
