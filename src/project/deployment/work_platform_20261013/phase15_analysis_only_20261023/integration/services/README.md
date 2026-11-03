# 共享 PL 标量服务程序

本目录是实际可执行的 PL 微程序构建器，不是在 PS 执行 DSP 的替代实现。
数学运算由 `scalar_engine.cpp` 执行。未修改冻结基线、核心、RTL、调度器或旧功能审计表。

已实现并通过本机同源 C 核心/独立 NumPy 数值验证：

|服务|功能及单位|1025 bin 已测分片数|
|---|---|---:|
|copy / freeze|拷贝当前功率谱；完成后不再提交即可冻结，不停止采集|81|
|peak_hold|逐 bin 最大功率；重装/清除历史后重新开始|113|
|EMA|指数功率谱平均，默认 alpha=0.2，零历史启动|145|
|smoothing|三点 [1,2,1]/4 平滑，两个端点保持|193|
|octave / third_octave|FFT-bin PSD 积分的相对倍频程能量；不是 IEC 滤波器组|92 / 74|
|shape|功率质心、平坦度、峰 bin 功率、峰频率|241|
|flux_delta|正向频谱通量、绝对差总和、均方根差；历史自动更新|209|

分片数来自每次最多 64 条微指令的真实 C 执行，不是 FPGA 时钟周期。测试共 15 项、7,229 个数值比较通过。
测试包含跨 slot 历史连续性、零谱、单 bin 信号及 generation 错配拒绝。
平坦度以 1e-20 地板防止 log(0)，限制在数学 [0,1] 范围。静音的质心/平坦度仍需上层有效性标志，不能解释成有效声学特征。
相对频带采用基 2 中心频率、半开频带，输出 FS²；无声学校准，不输出 dB SPL。

## 接入约束

- 读取 `stream_fft2048` 实际布局：每通道 stride 8192 words；4096 后为 1025 个 `[amplitude, PSD, binPower]`。
- 每项服务有四个连续、每个 16 words 的 slot 描述符，读权限由 source_slot 和调度器锁定，不接受任意 slot 读取。
- 需要核心 FLOAD target=2 受界限保护的 output/history 读取；STORE target=2 不允许。
- 输出/历史共享给四个来源 slot，只有单标量核串行写；上下文分别保存，不能并发运行同一服务的两个未完成事务。
- session/config/generation 绑定由核心检查；切换输入快照之前必须完成或明确取消旧事务。
- 指令每项少于 1024，预算每片 64；输出不超过 4096 words。完整谱服务要运行多个分片，不应对每个 64 指令分片提前公布最终结果。
- 不得把分片 DONE 前的历史/输出解释成原子最终结果。最终完成、DMA fence 后，发布服务 ID、源 frame/session/config 和有效标志。
- 私有输出均在 word 524288 以上。不同服务默认分配 24576 words，不重叠。
- 背景/谱差首帧是零历史 warm-up，不能直接用于异常报警。固定 A/B 对比可先加载 B，执行后丢弃更新历史或重新载入 B。
- 峰值保持/平均/通量历史在装载时清零。用户要求重新学习背景或重启事件会话时应增加 generation 并清零历史。
- 只计算输入混合频谱；不提供方向、声源分离、分类、绝对声级。

## 复现

在本目录使用已有 MinGW：

```
D:/mingw64/bin/g++.exe -std=c++17 -O2 -shared -DSIXMIC_NATIVE ../shared_backend/scalar_engine.cpp -o services_scalar.dll
python test_programs.py
python build_bundle.py
```

`service_bundle.bin` 为本机打包的原始 DDR 初始化内容，`service_bundle.json` 给出字偏移、长度、四槽描述符和 SHA256。
它只是配置数据，不是 Bitstream，也不代表已经在真实调度/AXI/板子运行。
本次生成使用实际采样率 49162010/1024；硬件音频时钟改变时必须重建频率/倍频程相关程序。

## 尚未完成的验证及范围

这些服务尚未做标量 RTL 联合测试、实际 FPGA 周期和整板验收。不能把 native PASS 写成完整 PL 上板通过。
实际分片请求、服务选择和结果发布需要父任务集成；本目录没有擅自修改调度器。
未在本目录实现 CSD/coherence、GCC、IFFT、谐波/基频、事件判决、传感器、RT60、STIPA 等其他功能，避免将有限服务冒充全部产品功能。
新增成本主要为私有 DDR 程序/上下文/历史；本程序不复制运算硬件。微指令访存开销明显，周期和 10Hz 余量必须由真实核及调度验证，不能按 Python 运行时间推断。
