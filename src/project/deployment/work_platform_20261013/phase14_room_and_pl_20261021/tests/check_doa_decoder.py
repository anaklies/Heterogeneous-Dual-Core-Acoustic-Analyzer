from pathlib import Path
import sys,ctypes,subprocess,json,hashlib
import numpy as np
sys.dont_write_bytecode=True
P=Path(__file__).resolve().parents[1];B=P.parent
sys.path.insert(0,str(B/'phase12m_product_algorithm_acceptance_20261021'))
import mcontext
from features import template,GRID,MIC,PAIRS,C
from model_j import torch
from infer_j import decode_output
from minimal_fix_i import weighted_decode
D=P/'pl_system/doa';D.mkdir(parents=True,exist_ok=True)
def literal(x):
    s=format(float(np.float32(x)),'.9g');return s+('f' if '.' in s or 'e' in s else '.0f')
header='// Staticfixedarray geometry, noscene truth.\n'
header+='static const float SINE[4096]={'+','.join(literal(x) for x in np.sin(np.arange(4096)*2*np.pi/4096))+'};\n'
for name,a in [('PAIR_DELTA',MIC[PAIRS[:,1]]-MIC[PAIRS[:,0]]),('GRID_ROM',GRID)]:
    header+=f'static const float {name}[{len(a)}][3]={{'+','.join('{'+','.join(map(literal,r))+'}' for r in a)+'};\n'
(D/'doa_rom.h').write_text(header)
bank=np.clip(np.rint(template(GRID)*16384),-32768,32767).astype(np.int16)
assert bank.shape==(614,15,2,63)
(P/'examples/doa_bank_q14.bin').write_bytes(bank.astype('<i2').tobytes())
subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-shared',str(D/'doa_first.cpp'),'-o',str(D/'doa_first.dll')],check=True)
fn=ctypes.CDLL(str(D/'doa_first.dll')).doa_first
fn.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_float,ctypes.c_float,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
def run(v,valid=True):
    v=np.ascontiguousarray(v,dtype=np.float32);out=np.zeros(9,np.float32)
    fn(v.ctypes.data,bank.ctypes.data,C,.1,1,int(valid),out.ctypes.data);return out
def angle(a,b):return float(np.degrees(np.arccos(np.clip(np.dot(a,b)/np.linalg.norm(a)/np.linalg.norm(b),-1,1))))
rows=[]
for kind in ['speech','broad']:
    raw=np.fromfile(B/f'phase13_pl_port_20261021/nn/hls_parallel/variant4/{kind}_output_q.bin',dtype='<i2')
    z=raw[:51030].reshape(1,15,2,63,27).astype(float)/8192
    support=raw[51030:76545].reshape(1,15,63,27).astype(float)/1024
    act=raw[76545:76572].reshape(1,27).astype(float)/1024
    count=raw[76572:].reshape(1,4).astype(float)/1024
    pred={k:torch.tensor(v,dtype=torch.float32) for k,v in dict(z=z,support=support,activity=act,count=count).items()}
    gold=decode_output(pred,.1,.5)[0]
    s=torch.sigmoid(pred['support']).mean(1).numpy()[0];a=torch.sigmoid(pred['activity']).numpy()[0]
    w=s*(s>=.5)*a[None];mass=w.sum();v=(pred['z'].numpy()[0]*w[None,None]).sum(-1)*(63/mass)
    out=run(v);expected=np.asarray(gold['directions'])[0]
    error=angle(out[2:5],expected)
    assert out[0] and error<=1 and abs(out[1]-gold['qualities'][0])<2e-4,(kind,out,error)
    rows.append(dict(id=kind,angleVsFrozenDecoderDegrees=error,scoreAbsoluteDifference=float(abs(out[1]-gold['qualities'][0]))))
for label,u in [('northpole',[0,0,1]),('southpole',[0,0,-1]),('seam',[np.cos(np.deg2rad(179)),np.sin(np.deg2rad(179)),0])]:
    v=template(np.array(u)[None])[0];out=run(v);error=angle(out[2:5],u)
    assert out[0] and error<1,(label,out,error)
    rows.append(dict(id=label,syntheticUnitOnly=True,angleErrorDegrees=error))
assert not run(np.zeros((15,2,63)))[0]
assert not run(template(np.array([[1,0,0]]))[0],False)[0]
result=dict(status='C_GOLDEN_PASS',rows=rows,coarseBankBytes=bank.nbytes,coarseBankSHA256=hashlib.sha256(bank.tobytes()).hexdigest(),
            bankSoundSpeed=float(C),dynamicSoundSpeedBankGenerationImplemented=False,fullPCMRTL=False,notTrackIDs=True)
(P/'tests/doa_decoder.json').write_text(json.dumps(result,indent=2))
print('FIRST_DOA_DECODER_C_PASS',len(rows),'cases;nominalspeedbankonly')
