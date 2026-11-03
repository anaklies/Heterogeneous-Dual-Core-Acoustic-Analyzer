# SRP-DNN signed16权重导出及最小验证

当前模型：冻结J `small_seed1.pt`，SHA256 `b3e8a9f11c6d0a4d4742b0d18c7c5888ac24fa2c12a0a1acc7fdc7e1a56efcce`。
无训练、无修改旧模型。参数 **30958**，signed16权重 **61916 B**，原float32 **123832 B**。

## 导出定义

每个state tensor独立使用幂次二scale，`exponent=floor(log2(32767/max(abs(w))))`。
整数 `q=roundTiesToEven(w*2^exponent)`，范围[-32767,32767]；还原 `q*2^-exponent`。
实际无饱和。零tensor exponent=0。bias也独立量化，不能直接按输入/乘积scale相加，硬件必须显式对齐。
weights_i16.bin是little-endian连续int16，weights_i16.mem每行一word；tensor_manifest记录形状、offset和scale。
12个bank文件按全局i%12交织，不承诺它直接满足所有卷积读端口调度。权重和算子形状按PyTorch原始顺序。

## 六个有限输入结果

复用M三个房间的speech/broad各一份，使用其最后11776样本；真实STFT、pair_features、原decode_output和输入守卫。
权重量化后**还原为float32再运行**。accepted单主方向坐标变化 0/6，最大角差 0.00000085°；
phase输出最大绝对差 0.00027287006。所有逐层原始输出范围、最大/RMS误差和源数概率见weight_only_comparison.json。
这些复用数据不是新的独立泛化验证。主方向truth只是评估，不进入推理。

## 不能声称的结论

本次仅证明signed16权重离线打包及权重量化误差在6个输入上的表现。
激活量化、累加位宽/舍入/溢出、GELU/tanh/sigmoid LUT、GRU门及状态、1536 FFT、输入log/归一化、空间解码全部仍需完整定点黄金。
层hook记录原始模块输出（卷积/GELU之间），不是最终所有激活缓存。MAC数字继承M预算，并非RTL周期实测。
没有RTL综合、FPGA执行或完整网络移植。不能据权重缩小50%就声称DSP/BRAM整板已满足。

## C++原float前向链补充

已实现srpdnn_float.cpp，无Torch运行依赖：逐麦对Conv/GELU、depthwise、point、embedding、GRU、phase/support及跨15对activity/count。
卷积时间填充和裁剪保持因果索引；GRU保持PyTorch的r/z/n与reset-after含bias公式。权重C头由未改动float32 checkpoint导出。
对Mroom0_0一份实际特征执行完整15对模型，76576个输出元素均通过预设atol/rtol=2e-4的逐项比较；最终raw源数一致，首方向差0.0°。
详细误差与运行时间见CPP_COMPARISON.json。此为HLS友好固定形状C++参考，不含PCM/STFT/特征或最终空间解码硬件，没有综合、定点化或硬件吞吐证据。erf/exp/tanh的HLS可综合性和资源需实际工具验证；不能据C++通过宣称已移植PL。
