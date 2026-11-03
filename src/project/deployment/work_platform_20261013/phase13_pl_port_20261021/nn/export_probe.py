"""Signed-16, weight-only feasibility probe for frozen J SRP-DNN.

The network executes with dequantized weights and floating-point activations.
This is not full fixed-point inference or hardware acceptance.
"""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import math
import time
import numpy as np

P = Path(__file__).resolve().parent
B = P.parent.parent
J = B / 'phase12j_daily_srp_dnn_20261020'
H = B / 'phase12h_srp_dnn_salsa_20261020'
I = B / 'phase12i_srp_dnn_failure_diagnosis_20261020'
M = B / 'phase12m_product_algorithm_acceptance_20261021'
sys.path[:0] = [str(J), str(H), str(I), str(M)]
from model_j import SmallSRPDNN, torch, pair_features
from infer_j import decode_output
from features import stft
from quality_m import signal_quality, accepted_direction


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(name, value):
    (P / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def quantize(a):
    """Per tensor, symmetric [-32767,32767], LSB=2**(-exponent)."""
    a = np.asarray(a, dtype=np.float64)
    maximum = float(np.max(np.abs(a))) if a.size else 0.
    exponent = math.floor(math.log2(32767. / maximum)) if maximum else 0
    scale = math.ldexp(1., exponent)
    q64 = np.rint(a * scale)
    assert np.all(abs(q64) <= 32767), 'Unexpected quantization overflow'
    q = q64.astype('<i2')
    dequantized = q.astype(np.float64) / scale
    assert np.max(np.abs(dequantized-a), initial=0) <= .5/scale + 1e-12
    return q, exponent, dequantized.astype(np.float32)


def output_stats(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    delta = b-a
    return dict(shape=list(a.shape), originalAbsMax=float(abs(a).max()),
                maximumAbsoluteError=float(abs(delta).max()),
                RMSAbsoluteError=float(np.sqrt(np.mean(delta*delta))),
                meanAbsoluteError=float(abs(delta).mean()))


def install_trace(model):
    values = {}
    handles = []
    for name, module in model.named_children():
        def record(m, args, out, key=name):
            # For GRU, first tuple element is all timestep outputs.
            if isinstance(out, tuple):
                out = out[0]
            values[key] = out.detach().cpu().numpy().copy()
        handles.append(module.register_forward_hook(record))
    return values, handles


def direction_angles(u, v):
    u = np.asarray(u).reshape(-1, 3)
    v = np.asarray(v).reshape(-1, 3)
    if not len(u) or not len(v):
        return None
    return float(np.degrees(np.arccos(np.clip(u[0] @ v[0], -1, 1))))


def main():
    P.mkdir(parents=True, exist_ok=True)
    assert not (P/'tensor_manifest.json').exists(), 'Use a new output directory rather than overwrite export'
    weight = J/'models/small_seed1.pt'
    original_state = torch.load(weight, map_location='cpu', weights_only=True)
    quantized_state = {}
    tensors = []
    packed = []
    float_words = []
    offset = 0
    for name, value in original_state.items():
        a = value.detach().cpu().numpy()
        q, exponent, deq = quantize(a)
        quantized_state[name] = torch.from_numpy(deq.copy())
        packed.append(q.reshape(-1))
        float_words.append(a.astype('<f4').reshape(-1))
        tensors.append(dict(name=name, shape=list(a.shape), elements=a.size,
            offsetWords16=offset, offsetBytes=offset*2, signedBits=16,
            fractionalExponent=exponent, reconstruction='q * 2**(-fractionalExponent)',
            rounding='nearest ties to even', saturationCount=0,
            originalAbsMax=float(abs(a).max()), maximumAbsoluteError=float(abs(deq-a).max()),
            quantizedMin=int(q.min()), quantizedMax=int(q.max()),
            layout='original PyTorch state tensor C-order; GRU rows r,z,n'))
        offset += a.size
    packed = np.concatenate(packed).astype('<i2')
    assert len(packed) == 30958
    (P/'weights_i16.bin').write_bytes(packed.tobytes())
    (P/'weights_f32_reference.bin').write_bytes(np.concatenate(float_words).astype('<f4').tobytes())
    (P/'weights_i16.mem').write_text(''.join(f'{int(v)&65535:04x}\n' for v in packed), encoding='ascii')
    # Optional cyclic 12-lane memory export. Each tensor starts at its manifest offset.
    for lane in range(12):
        bank = packed[lane::12]
        (P/f'weight_bank_{lane:02}.mem').write_text(''.join(f'{int(v)&65535:04x}\n' for v in bank), encoding='ascii')
    reconstructed = np.frombuffer((P/'weights_i16.bin').read_bytes(), '<i2')
    assert np.array_equal(reconstructed, packed)
    original = SmallSRPDNN().eval()
    original.load_state_dict(original_state)
    quantized = SmallSRPDNN().eval()
    quantized.load_state_dict(quantized_state)
    original_trace, handles0 = install_trace(original)
    quantized_trace, handles1 = install_trace(quantized)
    rows = []
    for room in range(3):
        for kind, case in [('speech',0),('broad',1)]:
            path = M/f'data/cases/Mroom{room}_{case}.npz'
            pcm = np.load(path)['pcm'][-11776:]
            x = torch.from_numpy(pair_features(stft(pcm)))[None]
            start = time.perf_counter()
            with torch.no_grad():
                y0 = original(x)
                y1 = quantized(x)
            elapsed = time.perf_counter()-start
            d0 = decode_output(y0, .1, .5)[0]
            d1 = decode_output(y1, .1, .5)[0]
            quality = signal_quality(pcm)
            u0 = accepted_direction(d0['directions'], quality)
            u1 = accepted_direction(d1['directions'], quality)
            truth = np.asarray([math.cos(math.radians(35)),math.sin(math.radians(35)),0])
            row = dict(id=f'Mroom{room}_{case}', kind=kind,
                inputFile=str(path), inputFileSHA256=sha(path),
                inputPCMInt32LESHA256=hashlib.sha256(pcm.astype('<i4').tobytes()).hexdigest(),
                floatRawDirections=np.asarray(d0['directions']).tolist(),
                quantizedWeightRawDirections=np.asarray(d1['directions']).tolist(),
                floatAcceptedMainDirection=u0.tolist(), quantizedWeightAcceptedMainDirection=u1.tolist(),
                acceptedMainDirectionDifferenceDegrees=direction_angles(u0,u1),
                floatMainTruthErrorDegrees=direction_angles(u0,truth),
                quantizedWeightMainTruthErrorDegrees=direction_angles(u1,truth),
                floatRawSourceCount=d0['sourceCount'], quantizedWeightRawSourceCount=d1['sourceCount'],
                floatCountProbabilities=d0.get('countProbabilities',[]).tolist(),
                quantizedWeightCountProbabilities=d1.get('countProbabilities',[]).tolist(),
                outputDifferences={key:output_stats(y0[key].numpy(), y1[key].numpy()) for key in y0},
                moduleActivationDifferences={key:output_stats(original_trace[key], quantized_trace[key]) for key in original_trace},
                CPUSecondsBothModelsAndHooks=elapsed,
                guardFlags=quality['flags'], inferenceThreshold=.1, activityThreshold=.5,
                fullFixedPoint=False, hardwareExecuted=False)
            rows.append(row)
            print(row['id'], len(u0), len(u1), row['acceptedMainDirectionDifferenceDegrees'], flush=True)
    for handle in handles0+handles1:
        handle.remove()
    inventory = [dict(name=name, module=str(module), parameters=sum(p.numel() for p in module.parameters()))
                 for name,module in original.named_children()]
    assert sum(v['parameters'] for v in inventory)==30958
    manifest = dict(sourceCheckpoint=str(weight),sourceCheckpointSHA256=sha(weight),
        sourceFiles={str(p):sha(p) for p in [J/'model_j.py', J/'infer_j.py', H/'features.py', M/'quality_m.py']},
        parameters=30958, int16WeightBytes=packed.nbytes, float32WeightBytes=30958*4,
        tensors=tensors, layers=inventory, bankCount=12,
        bankLayout='global word i -> bank i%12, address floor(i/12); no per-tensor padding',
        MACsPerFull15PairWindow=28688448, MACSource='inherited Phase12M budget, not remeasured RTL',
        activationQuantized=False, nonlinearLUTValidated=False, GRUGatesFixedPointValidated=False,
        fixedPointFrontendValidated=False, PLImplemented=False, noRetraining=True,
        probeScope='weight quantization followed by float32 dequantized execution only')
    save('tensor_manifest.json',manifest)
    save('weight_only_comparison.json',dict(cases=6,rows=rows,scope=manifest['probeScope']))
    maxdirection = max(v['acceptedMainDirectionDifferenceDegrees'] or 0 for v in rows)
    changed = sum(v['floatAcceptedMainDirection']!=v['quantizedWeightAcceptedMainDirection'] for v in rows)
    max_output = max(v['outputDifferences']['z']['maximumAbsoluteError'] for v in rows)
    save('SUMMARY.json',dict(cases=6,allExpectedParameterWordsRoundTrip=True,
        sourceCheckpointSHA256=sha(weight),signed16Bytes=packed.nbytes,
        acceptedMainDirectionCoordinatesChanged=changed,maximumMainDirectionDifferenceDegrees=maxdirection,
        maximumPhaseOutputAbsoluteError=max_output,
        acceptedDirectionCountChanged=sum(len(v['floatAcceptedMainDirection'])!=len(v['quantizedWeightAcceptedMainDirection']) for v in rows),
        rawSourceCountChanged=sum(v['floatRawSourceCount']!=v['quantizedWeightRawSourceCount'] for v in rows),
        PLDeploymentApproved=False,allFixedPointInferenceValidated=False))
    report = f'''# SRP-DNN signed16权重导出及最小验证

当前模型：冻结J `small_seed1.pt`，SHA256 `{sha(weight)}`。
无训练、无修改旧模型。参数 **30958**，signed16权重 **{packed.nbytes} B**，原float32 **123832 B**。

## 导出定义

每个state tensor独立使用幂次二scale，`exponent=floor(log2(32767/max(abs(w))))`。
整数 `q=roundTiesToEven(w*2^exponent)`，范围[-32767,32767]；还原 `q*2^-exponent`。
实际无饱和。零tensor exponent=0。bias也独立量化，不能直接按输入/乘积scale相加，硬件必须显式对齐。
weights_i16.bin是little-endian连续int16，weights_i16.mem每行一word；tensor_manifest记录形状、offset和scale。
12个bank文件按全局i%12交织，不承诺它直接满足所有卷积读端口调度。权重和算子形状按PyTorch原始顺序。

## 六个有限输入结果

复用M三个房间的speech/broad各一份，使用其最后11776样本；真实STFT、pair_features、原decode_output和输入守卫。
权重量化后**还原为float32再运行**。accepted单主方向坐标变化 {changed}/6，最大角差 {maxdirection:.8f}°；
phase输出最大绝对差 {max_output:.8g}。所有逐层原始输出范围、最大/RMS误差和源数概率见weight_only_comparison.json。
这些复用数据不是新的独立泛化验证。主方向truth只是评估，不进入推理。

## 不能声称的结论

本次仅证明signed16权重离线打包及权重量化误差在6个输入上的表现。
激活量化、累加位宽/舍入/溢出、GELU/tanh/sigmoid LUT、GRU门及状态、1536 FFT、输入log/归一化、空间解码全部仍需完整定点黄金。
层hook记录原始模块输出（卷积/GELU之间），不是最终所有激活缓存。MAC数字继承M预算，并非RTL周期实测。
没有RTL综合、FPGA执行或完整网络移植。不能据权重缩小50%就声称DSP/BRAM整板已满足。
'''
    (P/'REPORT.md').write_text(report,encoding='utf-8')
    files = {p.name:sha(p) for p in sorted(P.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt'}
    (P/'SHA256SUMS.txt').write_text(''.join(f'{h}  {name}\n' for name,h in files.items()),encoding='utf-8')
    print('WEIGHT_EXPORT_PROBE_COMPLETE',flush=True)


if __name__=='__main__':
    main()
