"""New fixed FFT -> existing features/NN/DOA, one inherited PCM window only.

This is a C-model affected-path check, never continuous RTL or room acceptance.
"""
from pathlib import Path
import ctypes, hashlib, json, subprocess, sys
import numpy as np
sys.dont_write_bytecode = True
P = Path(__file__).resolve().parents[1]
B = P.parent
sys.path.insert(0, str(B/'phase12m_product_algorithm_acceptance_20261021'))
import mcontext
from features import stft

backend = sys.argv[1] if len(sys.argv)>1 else 'fixed'
assert backend in ('fixed','burst')
pcm = np.fromfile(P/'examples/feature_pcm.bin', '<i4').reshape(11776, 6)
fixed = np.fromfile(P/f'results/{backend}_fft_stft.bin', '<f4').reshape(6, 27, 63, 2)
fixed = np.ascontiguousarray(fixed.transpose(0, 2, 1, 3))
expected = stft(pcm.astype(np.float64)/8388608.)*8388608.
# The exact PCM unit convention is checked against the inherited stored input,
# instead of allowing scale mismatch to hide behind neural normalization.
reference = np.ascontiguousarray(np.stack([expected.real, expected.imag], -1), dtype=np.float32)
fn = ctypes.CDLL(str(P/'hls/neural_features.dll')).neural_features
fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
def features(x):
    y = np.zeros(153090, np.int16)
    clips = ctypes.c_uint()
    fn(x.ctypes.data, y.ctypes.data, ctypes.byref(clips))
    assert not clips.value
    return y
fq, rq = features(fixed), features(reference)
old = np.fromfile(B/'phase13_pl_port_20261021/nn/fixed/room0_speech_input_q11.bin', '<i2')
reference_difference = int(np.max(abs(rq.astype(int)-old.astype(int))))
assert reference_difference <= 1, reference_difference
input_path = P/f'results/{backend}_fft_feature_q11.bin'
fq.astype('<i2').tofile(input_path)
window = P/'pl_system/nn_window'
output_path = P/f'results/{backend}_frontend_window.bin'
subprocess.run([str(window/'nn_window.exe'), str(input_path), str(output_path)], check=True)
raw = output_path.read_bytes()
vector = np.frombuffer(raw[76576*2:76576*2+1890*4], '<f4').copy()
baseline = (window/'window_output.bin').read_bytes()
old_vector = np.frombuffer(baseline[76576*2:76576*2+1890*4], '<f4').copy()
meta = np.frombuffer(raw[76576*2+1890*4:76576*2+1890*4+40], '<u8')
decoder = ctypes.CDLL(str(P/'pl_system/doa/doa_first.dll')).doa_first
decoder.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_float,ctypes.c_float,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
bank = np.fromfile(P/'examples/doa_bank_q14.bin', '<i2')
def decode(v):
    out = np.zeros(9, np.float32)
    decoder(v.ctypes.data,bank.ctypes.data,343.,.1,1,1,out.ctypes.data)
    return out
out, old_out = decode(vector), decode(old_vector)
angle = float(np.degrees(np.arccos(np.clip(np.dot(out[2:5],old_out[2:5])/
              np.linalg.norm(out[2:5])/np.linalg.norm(old_out[2:5]), -1, 1))))
assert bool(meta[2]) and out[0] and old_out[0]
assert angle <= 1, angle
result = dict(status='PASS_ONE_CMODEL_AFFECTED_PCM_WINDOW',backend=backend,case='inherited_room0_speech',
    pcmSHA256=hashlib.sha256(pcm.tobytes()).hexdigest(),fftTransforms=162,
    fftMaximumRawCountError=float(np.max(abs(fixed-reference))),
    featuresMaximumDifferenceLSB=int(np.max(abs(fq.astype(int)-rq.astype(int)))),
    floatFrontendVsSavedInputMaximumLSB=reference_difference,
    directionChangeDegrees=angle,baseline=old_out.tolist(),fixed=out.tolist(),
    fullRTL=False,continuous10Hz=False,physicalBoard=False,
    warning='One C-model regression only; low-energy phase changes need wider coverage before freeze.')
(P/f'tests/{backend}_frontend.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
