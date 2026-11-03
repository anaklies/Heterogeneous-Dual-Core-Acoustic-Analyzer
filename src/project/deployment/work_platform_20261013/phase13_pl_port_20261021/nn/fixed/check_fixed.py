"""Build fixed-point C++ model, test primitives, and compare two frozen inputs."""
from pathlib import Path
import sys
sys.dont_write_bytecode=True
P=Path(__file__).resolve().parent
N=P.parent
sys.path.insert(0,str(N))
from export_probe import (J,H,M,SmallSRPDNN,torch,pair_features,stft,
                          signal_quality,accepted_direction,decode_output,output_stats,
                          direction_angles,sha)
import json
import math
import subprocess
import time
import numpy as np

STAGES=['conv_affine','depth_affine','point_affine','embed_affine',
        'gru_input_affine','gru_hidden_affine','gru_reset_pre','gru_update_pre',
        'gru_new_pre','gru_hidden','phase_affine','support_affine',
        'global_mean','activity_affine','count_affine']


def save(name,value):
    (P/name).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')


def headers():
    manifest=json.loads((N/'tensor_manifest.json').read_text(encoding='utf-8'))
    words=np.fromfile(N/'weights_i16.bin','<i2')
    lines=['#ifndef SIXMIC_FIXED_WEIGHTS_H','#define SIXMIC_FIXED_WEIGHTS_H','#include <cstdint>']
    for item in manifest['tensors']:
        name='W_'+item['name'].replace('.','_').upper()
        values=words[item['offsetWords16']:item['offsetWords16']+item['elements']]
        lines.append(f'enum {{ {name}_FRAC={item["fractionalExponent"]} }};')
        lines.append(f'static const std::int16_t {name}[{len(values)}]={{')
        for i in range(0,len(values),12):
            lines.append('    '+','.join(str(int(v)) for v in values[i:i+12])+',')
        lines.append('};')
    lines.extend(['#endif',''])
    (P/'weights_fixed.h').write_text('\n'.join(lines),encoding='ascii')
    x=np.linspace(-8,8,4097)
    table_values={
        'GELU_Q10':np.rint(np.array([.5*v*(1+math.erf(v/math.sqrt(2))) for v in x])*1024).astype(np.int32),
        'SIGMOID_Q15':np.rint(32768/(1+np.exp(-x))).astype(np.int32),
        'TANH_Q14':np.rint(np.tanh(x)*16384).astype(np.int32)}
    lines=['#ifndef SIXMIC_NONLINEAR_LUT_H','#define SIXMIC_NONLINEAR_LUT_H','#include <cstdint>',
           '// Generated offline, round-to-nearest ties-to-even; no float runtime.']
    for name,values in table_values.items():
        lines.append(f'static const std::int32_t {name}[4097]={{')
        for i in range(0,len(values),12):
            lines.append('    '+','.join(str(int(v)) for v in values[i:i+12])+',')
        lines.append('};')
    lines.extend(['#endif',''])
    (P/'nonlinear_lut.h').write_text('\n'.join(lines),encoding='ascii')


def compile_run():
    compiler='D:/mingw64/bin/g++.exe'
    jobs=[(['srpdnn_fixed.cpp','run_fixed.cpp'],'nn_fixed.exe'),
          (['primitive_tests.cpp'],'primitive_tests.exe')]
    logs=[]
    for sources,out in jobs:
        command=[compiler,'-O2','-std=c++17','-fno-fast-math']+[str(P/name) for name in sources]+['-o',str(P/out)]
        r=subprocess.run(command,capture_output=True,text=True)
        logs.append(' '.join(command)+'\n'+r.stdout+r.stderr)
        r.check_returncode()
    (P/'compile.log').write_text('\n'.join(logs),encoding='utf-8')
    r=subprocess.run([str(P/'primitive_tests.exe')],capture_output=True,text=True,check=True)
    (P/'primitive_tests.log').write_text(r.stdout+r.stderr,encoding='utf-8')
    return json.loads(r.stdout)


def main():
    assert not (P/'FIXED_COMPARISON.json').exists(),'Preserve completed probe'
    rules=dict(input=dict(bits=16,fraction=11),postGELU=dict(bits=16,fraction=10),
        GRUHidden=dict(bits=16,fraction=14),GRUGatePreactivation=dict(bits=16,fraction=10),
        phase=dict(bits=16,fraction=13),logits=dict(bits=16,fraction=10),
        affineAccumulatorBits=64,weights='per-tensor signed16 power-of-two scale inherited unmodified',
        sigmoid=dict(outputFraction=15,storedIntermediateBits=32),
        LUT=dict(points=4097,inputMinimum=-8,inputMaximum=8,inputFraction=10,inputStepInteger=4,
                 interpolation='linear two fractional bits; signed nearest ties away from zero'),
        rounding='input and offline tables nearest ties even; runtime rescale/interpolation nearest ties away from zero',
        noTraining=True,noHoldoutScaleTuning=True)
    save('FIXED_RULES.json',rules)
    headers()
    primitives=compile_run()
    model=SmallSRPDNN().eval()
    model.load_state_dict(torch.load(J/'models/small_seed1.pt',weights_only=True,map_location='cpu'))
    rows=[]
    for case,kind in [(0,'speech'),(1,'broad')]:
        path=M/f'data/cases/Mroom0_{case}.npz'
        pcm=np.load(path)['pcm'][-11776:]
        features=pair_features(stft(pcm))
        raw=np.rint(features.astype(float)*2048)
        clipped=int(np.sum((raw<-32768)|(raw>32767)))
        q=np.clip(raw,-32768,32767).astype('<i2')
        stem=f'room0_{kind}'
        q.tofile(P/(stem+'_input_q11.bin'))
        start=time.perf_counter()
        subprocess.run([str(P/'nn_fixed.exe'),str(P/(stem+'_input_q11.bin')),
                        str(P/(stem+'_output_q.bin')),str(P/(stem+'_stats.txt'))],check=True)
        elapsed=time.perf_counter()-start
        out=np.fromfile(P/(stem+'_output_q.bin'),'<i2')
        counts=np.loadtxt(P/(stem+'_stats.txt'),dtype=np.int64)
        assert out.size==76576 and counts.size==18
        with torch.no_grad():
            reference=model(torch.from_numpy(features)[None])
        actual={}
        stats={}
        offset=0
        for key in ['z','support','activity','count']:
            expected=reference[key].numpy()
            fraction=13 if key=='z' else 10
            value=(out[offset:offset+expected.size].astype(np.float32)/(1<<fraction)).reshape(expected.shape)
            offset+=expected.size
            actual[key]=torch.from_numpy(value.copy())
            stats[key]=output_stats(expected,value)
        d0=decode_output(reference,.1,.5)[0]
        d1=decode_output(actual,.1,.5)[0]
        quality=signal_quality(pcm)
        u0=accepted_direction(d0['directions'],quality)
        u1=accepted_direction(d1['directions'],quality)
        row=dict(id=f'Mroom0_{case}',kind=kind,inputFile=str(path),inputFileSHA256=sha(path),
            fixedFeatureFileSHA256=sha(P/(stem+'_input_q11.bin')),inputFeatureSaturations=clipped,
            saturations=dict(zip(STAGES,counts[:15].tolist())),
            nonlinearDomainClamps=dict(zip(['gelu','sigmoid','tanh'],counts[15:].tolist())),
            outputDifferences=stats,floatAcceptedMainDirection=u0.tolist(),fixedAcceptedMainDirection=u1.tolist(),
            acceptedDirectionDifferenceDegrees=direction_angles(u0,u1),
            floatRawSourceCount=d0['sourceCount'],fixedRawSourceCount=d1['sourceCount'],
            floatCountProbabilities=d0['countProbabilities'].tolist(),
            fixedCountProbabilities=d1['countProbabilities'].tolist(),
            floatQualities=d0['qualities'],fixedQualities=d1['qualities'],
            CPUSecondsIncludingProcessStartup=elapsed,
            full15Pairs=True,integerNetworkCore=True,floatPCMFeatureFrontend=True,
            originalFloatSpatialDecoder=True,hardwareExecuted=False)
        rows.append(row)
        print(kind,'direction_delta_deg',row['acceptedDirectionDifferenceDegrees'],'saturations',sum(row['saturations'].values()),flush=True)
    sources=[P/'srpdnn_fixed.cpp',P/'srpdnn_fixed.h',P/'run_fixed.cpp',P/'weights_fixed.h',P/'nonlinear_lut.h',
             J/'model_j.py',J/'models/small_seed1.pt',N/'tensor_manifest.json',N/'weights_i16.bin']
    save('FIXED_COMPARISON.json',dict(rules=rules,sourceHashes={str(p):sha(p) for p in sources},
        primitiveTests=primitives,cases=2,rows=rows,
        fullFixedPointPCMToDOA=False,NNArithmetic='integer only',fixedPointInferenceCoreImplemented=True,
        HLSExecuted=False,PLImplemented=False,resourceFitPassed=False,hardware10HzValidated=False))
    write_report(rows,primitives)
    files={p.name:sha(p) for p in sorted(P.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt'}
    (P/'SHA256SUMS.txt').write_text(''.join(f'{h}  {n}\n' for n,h in files.items()),encoding='utf-8')
    print('INTEGER_NN_CORE_PROBE_COMPLETE',flush=True)


def write_report(rows,primitives):
    lines=['# Integer固定点SRP-DNN最小黄金验证','',
        '本目录仅新增整数网络核心，不修改旧nn源码、模型或报告。不训练，不根据两份测试输入调整尺度。','',
        '## 数值定义','',
        '- 输入signed16 Q11；Conv/Depth/Point/Embed的GELU输出Q10。',
        '- GRU输入/hidden两条仿射分别对齐到Q10；hidden Q14；r/z sigmoid为Q15正整数（32位容器），候选tanh Q14。',
        '- GRU保持PyTorch reset-after：r乘完整hidden仿射含b_hn；h=n+z*(h-n)。',
        '- phase=2*tanh，输出Q13；support/activity/count logits Q10；globalhidden先整型求和后除15并舍入。',
        '- 所有MAC用int64；bias先对齐到乘积小数位，再统一缩放。运行时除2^k采用最近数/半值远离零；输入和离线量化采用nearest-ties-even。',
        '- 非线性三个4097点LUT，Q10输入覆盖[-8,8]，间距4整数LSB，2bit线性插值。GELU区外用0/x，tanh区外用±1，sigmoid区外用0/1。域夹紧计数与int16算术饱和计数分离。',
        '- 输出二进制顺序phase/support/activity/count，shape与原J相同；各自scale见FIXED_RULES.json。','',
        '## 测试','',
        f'基础算术测试：{json.dumps(primitives,ensure_ascii=False)}。','',
        '两份输入均为已有Mroom0 speech/broad的相同末11776样本，先用原浮点STFT/pair_features再量化Q11。',
        '网络C++运行路径不含float/double、erf/exp/tanh或Torch；仅整型MAC、整数缩放、常量LUT与查表插值。',
        '输出还原到float只供原decode_output与现有输入质量守卫做离线对照，因此不是完整PCM→DOA定点验收。','']
    for row in rows:
        lines += [f'### {row["id"]} {row["kind"]}',
            f'- 接受主方向差：{row["acceptedDirectionDifferenceDegrees"]}°；raw源数原/新：{row["floatRawSourceCount"]}/{row["fixedRawSourceCount"]}。',
            f'- 输入饱和：{row["inputFeatureSaturations"]}；各级算术饱和：{json.dumps(row["saturations"])}。',
            f'- 非线性域夹紧：{json.dumps(row["nonlinearDomainClamps"])}。',
            '- 输出最大差：'+', '.join(f'{k}={v["maximumAbsoluteError"]:.7g}' for k,v in row['outputDifferences'].items())+'。','']
    lines += ['## 边界','',
        '只有2份原有输入，不是独立泛化测试。没有HLS、RTL、综合、布局、资源或10Hz证据。',
        '固定12输出lane微架构必须对本整数黄金逐项比较；不能以C++整数正确代替实际硬件等价和吞吐。',
        '全链仍缺定点FFT/特征归一化、实际空间解码、质量守卫和真实PCM调度。']
    (P/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
