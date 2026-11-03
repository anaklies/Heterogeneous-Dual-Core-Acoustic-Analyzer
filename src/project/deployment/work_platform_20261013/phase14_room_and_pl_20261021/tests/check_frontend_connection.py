"""One affected warm PCM window through the new frontend and existing cores.

No new rooms, training, RTL audio simulation or hardware performance claim.
"""
from pathlib import Path
import ctypes,hashlib,json,subprocess,sys
import numpy as np
sys.dont_write_bytecode=True
P=Path(__file__).resolve().parents[1]
B=P.parent
sys.path.insert(0,str(B/'phase12m_product_algorithm_acceptance_20261021'))
import mcontext
from features import stft,C
from model_j import pair_features
from quality_m import signal_quality

pcm=np.fromfile(P/'examples/frontend_window1.bin','<i4').reshape(11776,6)
z=np.fromfile(P/'results/frontend_pipe_warm_stft.bin','<f4').reshape(6,63,27,2)
cold=np.fromfile(P/'results/frontend_pipe_cold_stft.bin','<f4').reshape(6,63,27,2)
assert np.array_equal(z[:,:,:15],cold[:,:,12:])
ref=stft(pcm)
reference=np.ascontiguousarray(np.stack([ref.real,ref.imag],-1),dtype=np.float32)
q_reference=np.clip(np.rint(pair_features(ref)*2048),-32768,32767).astype('<i2')
q_fixed=np.fromfile(P/'results/frontend_pipe_warm_q11.bin','<i2')
assert q_fixed.size==153090 and np.isfinite(z).all()
meta=np.fromfile(P/'results/frontend_pipe_warm_meta.bin','<u4')
assert meta[0]==0x53464631 and meta[10]==72 and meta[11]==90 and meta[13]==0
reference_path=P/'results/frontend_reference_q11.bin'
q_reference.tofile(reference_path)
nn=P/'pl_system/nn_window/candidate_bias_bram/nn_window.exe'
def network(path,out):
    subprocess.run([str(nn),str(path),str(out)],check=True)
    raw=out.read_bytes()
    v=np.frombuffer(raw[153152:153152+7560],'<f4').copy()
    m=np.frombuffer(raw[153152+7560:153152+7560+40],'<u8')
    return v,m
v0,m0=network(reference_path,P/'results/frontend_reference_nn.bin')
v1,m1=network(P/'results/frontend_pipe_warm_q11.bin',P/'results/frontend_actual_nn.bin')
quality=signal_quality(pcm)
bank=np.fromfile(P/'examples/doa_bank_q14.bin','<i2')
fn=ctypes.CDLL(str(P/'pl_system/doa/doa_first_shared.dll')).doa_first_shared
fn.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_float,ctypes.c_float,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
def decode(v,m):
    out=np.zeros(9,np.float32)
    fn(v.ctypes.data,bank.ctypes.data,C,.1,int(m[2]),int(quality['directionSupported']),out.ctypes.data)
    return out
out0,out1=decode(v0,m0),decode(v1,m1)
assert out0[0]==out1[0],(out0,out1)
angle=None
if out0[0]:
    angle=float(np.degrees(np.arccos(np.clip(np.dot(out0[2:5],out1[2:5])/
        np.linalg.norm(out0[2:5])/np.linalg.norm(out1[2:5]),-1,1))))
    assert angle<=1,(angle,out0,out1)
result=dict(status='PASS_ONE_AFFECTED_CMODEL_CONNECTION',
    pcmSHA256=hashlib.sha256(pcm.tobytes()).hexdigest(),
    computedTransforms=int(meta[10]),reusedTransforms=int(meta[11]),
    reusedComplexValues=6*63*15,
    reusedCacheBitExact=True,cFeatureReferenceBitExact=True,
    fftMaximumComponentErrorRawCounts=float(abs(z-reference).max()),
    featureMaximumDifferenceVsFloatingFrontendLSB=int(abs(q_fixed.astype(int)-q_reference.reshape(-1).astype(int)).max()),
    directionChangeDegrees=angle,baseline=out0.tolist(),frontend=out1.tolist(),
    qualityFlags=quality['flags'],qualityGuardPLImplemented=False,
    sourceTruthNotUsed=True,fullRTL=False,actualBoard=False,continuous10Hz=False,
    scope='PCM -> cached fixed FFT -> features -> fixedNN -> first direction C models; not board wiring')
(P/'tests/frontend_connection.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
