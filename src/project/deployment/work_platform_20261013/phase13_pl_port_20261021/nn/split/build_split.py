"""One structural ROM split. Original arithmetic and frozen probe stay unchanged."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import time
import numpy as np

P = Path(__file__).resolve().parent
N = P.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((N/'tensor_manifest.json').read_text(encoding='utf-8'))
    words = np.fromfile(N/'weights_f32_reference.bin', '<f4')
    header = ['#ifndef SIXMIC_SPLIT_FROZEN_NN_WEIGHTS_H',
              '#define SIXMIC_SPLIT_FROZEN_NN_WEIGHTS_H',
              '// Independent per-tensor ROM declarations; unchanged float32 bits.']
    arrays = []
    for tensor in manifest['tensors']:
        name = 'W_' + tensor['name'].replace('.', '_').upper()
        offset = tensor['offsetWords16']
        a = words[offset:offset+tensor['elements']]
        assert a.size==tensor['elements']
        header.append(f'static const float {name}[{a.size}] = {{')
        for i in range(0,len(a),8):
            header.append('    ' + ', '.join(f'{float(v):.9e}f' for v in a[i:i+8]) + ',')
        header.append('};')
        arrays.append(dict(name=name,elements=a.size,bytes=a.nbytes,
                           SHA256Float32LE=hashlib.sha256(a.tobytes()).hexdigest()))
    header.extend(['#endif',''])
    (P/'weights_float.h').write_text('\n'.join(header),encoding='ascii')
    source = (N/'srpdnn_float.cpp').read_text(encoding='utf-8')
    source = re.sub(r'NN_WEIGHTS\[OFF_([A-Z0-9_]+)\s*\+\s*([^\]]+)\]',
                    lambda m: f'W_{m[1]}[{m[2]}]',source)
    source = re.sub(r'NN_WEIGHTS\s*\+\s*OFF_([A-Z0-9_]+)',
                    lambda m:'W_'+m[1],source)
    assert 'NN_WEIGHTS' not in source and 'OFF_' not in source
    (P/'srpdnn_float.cpp').write_text(source,encoding='utf-8')
    (P/'srpdnn_float.h').write_bytes((N/'srpdnn_float.h').read_bytes())
    (P/'run_float.cpp').write_bytes((N/'run_float.cpp').read_bytes())
    begin = time.perf_counter()
    result = subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-std=c++17','-fno-fast-math',
                             str(P/'srpdnn_float.cpp'),str(P/'run_float.cpp'),'-o',str(P/'nn_float_split.exe')],
                            capture_output=True,text=True)
    (P/'compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    result.check_returncode()
    subprocess.run([str(P/'nn_float_split.exe'),str(N/'cpp_input_features.bin'),str(P/'cpp_outputs_split.bin')],check=True)
    actual=np.fromfile(P/'cpp_outputs_split.bin','<f4')
    original=np.fromfile(N/'cpp_outputs.bin','<f4')
    torchgold=np.fromfile(N/'torch_outputs.bin','<f4')
    assert actual.size==76576
    assert np.array_equal(actual,original), 'Structural split changed native output'
    np.testing.assert_allclose(actual,torchgold,atol=2e-4,rtol=2e-4)
    report=dict(
        sourceInputs={str(p):sha(p) for p in [N/'srpdnn_float.cpp',N/'srpdnn_float.h',N/'run_float.cpp',
            N/'weights_f32_reference.bin',N/'tensor_manifest.json',N/'cpp_input_features.bin',N/'cpp_outputs.bin',N/'torch_outputs.bin']},
        transformation='one monolithic NN_WEIGHTS ROM replaced by per-tensor W_* ROM declarations and direct references',
        parameterWords=sum(a['elements'] for a in arrays),arrays=arrays,
        unchangedAlgorithm=True,unchangedFloatingPointWeights=True,
        full15PairOutputElements=int(actual.size),
        nativeSplitVsOriginalBitExact=True,
        splitVsTorchMaxAbsoluteError=float(abs(actual-torchgold).max()),
        comparisonTolerance=dict(absolute=2e-4,relative=2e-4),
        compileAndRunWallSeconds=time.perf_counter()-begin,
        HLSExecuted=False,resourceFitPassed=False,hardwareThroughputPassed=False,
        originalProbePreserved=True)
    (P/'SPLIT_COMPARISON.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (P/'REPORT.md').write_text('''# 单次低成本ROM结构修复

本副本仅把30958-word整体权重表拆为state tensor独立`W_*`常量数组，消除每个outlined loop看到完整权重地址空间的结构诱因。
没有改变卷积、GELU、GRU、输出计算、权重、数据类型或运算次序。原nn源码和原HLS失败证据保持不变。

新入口：`split/srpdnn_float.cpp`、`split/srpdnn_float.h`、`split/weights_float.h`。
复现：`build_split.py`生成副本与头、原编译参数编译并比较。

相同实际M speech特征、完整15麦对76576输出：新旧native C++输出逐bit一致，与既有Torch黄金亦通过原atol/rtol=2e-4。
源码/输入/输出哈希及各ROM参数见`SPLIT_COMPARISON.json`。

本子任务没有执行HLS，不能宣称BRAM已经降低到器件预算，也没有关闭周期超限。仍需主智能体用相同HLS探针测量实际BRAM/DSP与延迟。
''' ,encoding='utf-8')
    files={p.name:sha(p) for p in sorted(P.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt'}
    (P/'SHA256SUMS.txt').write_text(''.join(f'{digest}  {name}\n' for name,digest in files.items()),encoding='utf-8')
    print('SPLIT_ROM_CPP_BITEXACT_PASS',actual.size,flush=True)


if __name__=='__main__':
    main()
