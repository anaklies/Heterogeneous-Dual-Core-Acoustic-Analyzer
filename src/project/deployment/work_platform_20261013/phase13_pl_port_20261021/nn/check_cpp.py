"""Compile the unchanged-float C++ model and compare all output tensors."""
from export_probe import *
import subprocess


def main():
    manifest = json.loads((P/'tensor_manifest.json').read_text())
    words = np.frombuffer((P/'weights_f32_reference.bin').read_bytes(),'<f4')
    header = ['#ifndef SIXMIC_FROZEN_NN_WEIGHTS_H', '#define SIXMIC_FROZEN_NN_WEIGHTS_H',
              '// Exact float32 round-trip constants from the unchanged J checkpoint.']
    for tensor in manifest['tensors']:
        name = tensor['name'].replace('.','_').upper()
        header.append(f'enum {{ OFF_{name} = {tensor["offsetWords16"]} }};')
    header.append(f'static const float NN_WEIGHTS[{len(words)}] = {{')
    for i in range(0,len(words),8):
        header.append('    '+', '.join(f'{float(v):.9e}f' for v in words[i:i+8])+',')
    header += ['};','#endif','']
    (P/'weights_float.h').write_text('\n'.join(header),encoding='ascii')
    result = subprocess.run(['D:/mingw64/bin/g++.exe','-O2','-std=c++17','-fno-fast-math',
                             str(P/'srpdnn_float.cpp'),str(P/'run_float.cpp'),'-o',str(P/'nn_float.exe')],
                            capture_output=True,text=True)
    (P/'cpp_compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    result.check_returncode()
    model = SmallSRPDNN().eval()
    model.load_state_dict(torch.load(J/'models/small_seed1.pt',weights_only=True,map_location='cpu'))
    path = M/'data/cases/Mroom0_0.npz'
    pcm = np.load(path)['pcm'][-11776:]
    x = pair_features(stft(pcm))
    x.astype('<f4').tofile(P/'cpp_input_features.bin')
    with torch.no_grad():
        expected = model(torch.from_numpy(x)[None])
    expected_numpy = {key:value.numpy() for key,value in expected.items()}
    np.concatenate([expected_numpy[key].reshape(-1) for key in ['z','support','activity','count']]).astype('<f4').tofile(P/'torch_outputs.bin')
    started = time.perf_counter()
    subprocess.run([str(P/'nn_float.exe'),str(P/'cpp_input_features.bin'),str(P/'cpp_outputs.bin')],check=True)
    elapsed = time.perf_counter()-started
    actual_words = np.fromfile(P/'cpp_outputs.bin','<f4')
    offset = 0
    stats = {}
    actual = {}
    # Tolerance fixed before numerical comparison; accumulation order differs
    # from Torch CPU reductions. Final decode is compared separately.
    tolerance = dict(absolute=2e-4,relative=2e-4)
    for key in ['z','support','activity','count']:
        expected_array = expected_numpy[key]
        a = actual_words[offset:offset+expected_array.size].reshape(expected_array.shape)
        offset += expected_array.size
        actual[key] = torch.from_numpy(a.copy())
        stats[key] = output_stats(expected_array,a)
        np.testing.assert_allclose(a,expected_array,atol=tolerance['absolute'],rtol=tolerance['relative'])
    assert offset==len(actual_words)
    d0=decode_output(expected,.1,.5)[0]
    d1=decode_output(actual,.1,.5)[0]
    assert d0['sourceCount']==d1['sourceCount']
    difference=direction_angles(d0['directions'],d1['directions'])
    assert difference is None or difference<.01
    save('CPP_COMPARISON.json',dict(cases=1,inputFile=str(path),inputFileSHA256=sha(path),
         featureInputSHA256=sha(P/'cpp_input_features.bin'),
         testedFull15Pairs=True,outputElements=int(offset),tolerance=tolerance,
         differences=stats,floatRawSourceCount=d0['sourceCount'],cppRawSourceCount=d1['sourceCount'],
         mainDirectionDifferenceDegrees=difference,CPUSecondsIncludingProcessStartup=elapsed,
         runtime='native C++ float reference, no Torch runtime',
         PLImplemented=False,synthesized=False,fixedPoint=False))
    with (P/'REPORT.md').open('a',encoding='utf-8') as f:
        f.write(f'''\n## C++原float前向链补充\n\n已实现srpdnn_float.cpp，无Torch运行依赖：逐麦对Conv/GELU、depthwise、point、embedding、GRU、phase/support及跨15对activity/count。\n卷积时间填充和裁剪保持因果索引；GRU保持PyTorch的r/z/n与reset-after含bias公式。权重C头由未改动float32 checkpoint导出。\n对Mroom0_0一份实际特征执行完整15对模型，{offset}个输出元素均通过预设atol/rtol=2e-4的逐项比较；最终raw源数一致，首方向差{difference}°。\n详细误差与运行时间见CPP_COMPARISON.json。此为HLS友好固定形状C++参考，不含PCM/STFT/特征或最终空间解码硬件，没有综合、定点化或硬件吞吐证据。erf/exp/tanh的HLS可综合性和资源需实际工具验证；不能据C++通过宣称已移植PL。\n''')
    files={p.name:sha(p) for p in sorted(P.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt'}
    (P/'SHA256SUMS.txt').write_text(''.join(f'{h}  {name}\n' for name,h in files.items()),encoding='utf-8')
    print(json.dumps(stats,indent=2))
    print('CPP_FLOAT_FULL15_FORWARD_PASS',offset,flush=True)


if __name__=='__main__':
    main()
