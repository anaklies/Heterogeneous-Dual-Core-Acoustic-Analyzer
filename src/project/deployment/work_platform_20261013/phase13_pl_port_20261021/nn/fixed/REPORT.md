# Integer固定点SRP-DNN最小黄金验证

本目录仅新增整数网络核心，不修改旧nn源码、模型或报告。不训练，不根据两份测试输入调整尺度。

## 数值定义

- 输入signed16 Q11；Conv/Depth/Point/Embed的GELU输出Q10。
- GRU输入/hidden两条仿射分别对齐到Q10；hidden Q14；r/z sigmoid为Q15正整数（32位容器），候选tanh Q14。
- GRU保持PyTorch reset-after：r乘完整hidden仿射含b_hn；h=n+z*(h-n)。
- phase=2*tanh，输出Q13；support/activity/count logits Q10；globalhidden先整型求和后除15并舍入。
- 所有MAC用int64；bias先对齐到乘积小数位，再统一缩放。运行时除2^k采用最近数/半值远离零；输入和离线量化采用nearest-ties-even。
- 非线性三个4097点LUT，Q10输入覆盖[-8,8]，间距4整数LSB，2bit线性插值。GELU区外用0/x，tanh区外用±1，sigmoid区外用0/1。域夹紧计数与int16算术饱和计数分离。
- 输出二进制顺序phase/support/activity/count，shape与原J相同；各自scale见FIXED_RULES.json。

## 测试

基础算术测试：{"integerChecks": 2162704, "GELUMaxAbsoluteError": 0.000944105945324, "sigmoidMaxAbsoluteError": 0.000335022909623, "tanhMaxAbsoluteError": 5.94933365314e-05, "status": "PASS"}。

两份输入均为已有Mroom0 speech/broad的相同末11776样本，先用原浮点STFT/pair_features再量化Q11。
网络C++运行路径不含float/double、erf/exp/tanh或Torch；仅整型MAC、整数缩放、常量LUT与查表插值。
输出还原到float只供原decode_output与现有输入质量守卫做离线对照，因此不是完整PCM→DOA定点验收。

### Mroom0_0 speech
- 接受主方向差：0.0°；raw源数原/新：1/1。
- 输入饱和：0；各级算术饱和：{"conv_affine": 0, "depth_affine": 0, "point_affine": 0, "embed_affine": 0, "gru_input_affine": 0, "gru_hidden_affine": 0, "gru_reset_pre": 0, "gru_update_pre": 0, "gru_new_pre": 0, "gru_hidden": 0, "phase_affine": 0, "support_affine": 0, "global_mean": 0, "activity_affine": 0, "count_affine": 0}。
- 非线性域夹紧：{"gelu": 497, "sigmoid": 310, "tanh": 2}。
- 输出最大差：z=0.002157733, support=0.005480766, activity=0.001321316, count=0.0002622604。

### Mroom0_1 broad
- 接受主方向差：8.537736462515939e-07°；raw源数原/新：1/1。
- 输入饱和：0；各级算术饱和：{"conv_affine": 0, "depth_affine": 0, "point_affine": 0, "embed_affine": 0, "gru_input_affine": 0, "gru_hidden_affine": 0, "gru_reset_pre": 0, "gru_update_pre": 0, "gru_new_pre": 0, "gru_hidden": 0, "phase_affine": 0, "support_affine": 0, "global_mean": 0, "activity_affine": 0, "count_affine": 0}。
- 非线性域夹紧：{"gelu": 227, "sigmoid": 322, "tanh": 0}。
- 输出最大差：z=0.002069041, support=0.004140377, activity=0.001081467, count=0.0002924204。

## 边界

只有2份原有输入，不是独立泛化测试。没有HLS、RTL、综合、布局、资源或10Hz证据。
固定12输出lane微架构必须对本整数黄金逐项比较；不能以C++整数正确代替实际硬件等价和吞吐。
全链仍缺定点FFT/特征归一化、实际空间解码、质量守卫和真实PCM调度。
