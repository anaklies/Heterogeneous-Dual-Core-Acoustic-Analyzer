# 完整15麦对NN与时间加权聚合

本目录继续已有V4整数核，未修改旧模型、固定点黄金、卷积/GRU公式或舍入规则。它是新的完整window计算候选，不等于整板通过或可烧录版本。

## 接口

`nn_window.h`中常量为实际shape：

- input：153090个signed16 Q11，顺序pair15×channel6×frequency63×time27。
- phase：51030个signed16 Q13，pair15×component2×frequency63×time27。
- support：25515个signed16 Q10 logits，pair15×frequency63×time27。
- logits：31个signed16 Q10，先27个globalactivity，再4个globalcount。
- vector：1890个IEEEfloat32，pair15×component2×frequency63，公式见下。
- metadata：5个uint64，依次massQ15、windowactivityQ15、activegate、非零TF权重数量、聚合sigmoid额外域夹紧数。
- counters：旧整数网络18个uint64计数，额外聚合不污染这些计数。

所有顶层数组通过真实AXI存储接口访问。phase/support/logits共用network bundle，vector/meta/counter共用aggregate bundle；输入独立features bundle。调用方必须提供完整输入、互不重叠且处于保留DDR区域的输出，以及帧/版本关联。它不是PC或PS执行的核心算法。

## 数学关系

逐频逐时的support先对15对的sigmoidQ15求和，门限使用`sum >=15*16384`（对应均值>=0.5）。与globalactivity的sigmoidQ15相乘，再舍入为Q15权重。`massQ15`是63×27权重之和。

输出vector满足：

`vector[p,c,f] =63*sum_t(phaseQ13[p,c,f,t]*weightQ15[f,t])/(8192*massQ15)`。

空间解码首轮评分为`dot(vector,template)/(15*63)`，与原minimal_fix_i.weighted_decode的归一化定义一致。质量门限及后续角度微调由真正的空间解码器负责，不在本核中制造DOA。

countsoftmax的活动门使用独立Q24指数LUT与稳定减最大值，输出活动Q15和`active >=0.5`标志。无权重时vector为0；下游必须同时检查活动标志、mass及输入质量，不能把非零globalcount当作确认的实际声源数量。

## 已完成的新验证

`check_window.py`只读取一份已经存在的speech Q11输入及原黄金二进制，不重跑训练、声学场景、旧primitive或旧RTL测试。

76576个NN输出和18旧计数逐位一致；1890个normalizedvector与整数聚合公式逐位一致。相对原float sigmoid形成的加权vector，最大差约3.23e-5；support>=0.5门控在此例无差异；mass相对差约7.12e-6。精确范围见C_ACCEPTANCE.json。

这些不是新独立声学泛化测试，也不是全PCM→DOA固定点通过。定点sigmoid和权重舍入在其他边界输入可能改变support门控或质量门限，未将此例推广为零误差保证。

## 构建

`probe.cfg`请求75MHz计算域，I2S采集时钟不在本模块内改变。HLS输出在独立`tmp/p15_nnwindow`；主任务仍需真实DDR/CDC、完整PCM/空间解码、全部P0节拍与整板资源时序验证。

本目录未运行RTL协同仿真或整板布局布线。C测试和HLS估算不能替代实际10Hz稳态输入验证。HLS接口寄存器偏移以其自动生成的driver头为准，不套用旧MUSIC邮箱ABI。

## 唯一一次75MHz HLS探测结果

`nn_window_csynth.rpt/xml`为本核真实HLS结果；`xnn_window_hw.h`为本次自动生成的控制寄存器映射。完整IP在`tmp/p15_nnwindow/hls/impl/ip/xilinx_com_hls_nn_window_1_0.zip`。

- 单个pair_forward实例，未复制15份核心。
- LUT 32721、FF 18411、DSP85、BRAM18K234；不是整板资源或Slice装箱结果。
- 目标13.333ns；HLS估计9.733ns；未布局布线。
- 完整window延迟4072037–45091668周期；启动间隔4072038–45091669周期。
- 75MHz下最短约54.29ms、最坏估算约601ms。不得以最短值宣称10Hz通过。
- 聚合循环334621周期。BRAM18K只余46块给其他算法及接口，整板集成风险较高。

只进行上述一次HLS综合。没有运行RTL协同仿真、全PCM回归或新整板实现。`HLS_ACCEPTANCE.json`明确保留fullSystem10Hz=false。
