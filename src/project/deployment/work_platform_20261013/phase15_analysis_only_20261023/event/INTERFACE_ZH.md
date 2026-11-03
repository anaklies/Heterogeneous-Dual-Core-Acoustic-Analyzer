# 有界事件功率检测 RTL

这是独立、可综合的 PL 统计量检测核，不是完整录音服务。输入为每个 1024 样本块**已经算好的六通道功率和八个频带功率**；本核不接收 PCM，不实现去直流、窗、FFT、功率生成、前 2 秒/后 3 秒存储、DDR、WAV、网络或故障语义判断。尚未接入实物或系统顶层。只新增本目录，旧 phase12n 参考和冻结记录不修改。

## 数据与时序约定

- `channel_power[c*32+:32]`：通道 c 的无符号 32 位功率；六通道同一缩放，核内 35 位精确求和。`background_power` 是此和的参考。因此本接口总功率地板也是六通道求和单位。
- `band_power[b*32+:32]`：频带 b 的无符号 32 位功率，已经跨六通道聚合，前端必须保证不溢出并保持每带缩放不变；频带参考使用相同单位。一个公共地板用于总功率及分带，各自上游缩放应保持兼容；本核不自行归一化。
- 固定频带索引继承软件参考：0:80–160、1:160–315、2:315–630、3:630–1250、4:1250–2500、5:2500–5000、6:5000–10000、7:10000–20000 Hz，左闭右开。实际频率边界及功率计算必须由前端实现。本核只对索引选择，不能声称任意 Hz 分辨率。
- `sample_timestamp` 是块首样本的 64 位无符号单调序号。第一个有效特征块接受任意起点；此后间隔必须严格等于配置 block_samples（参考为 1024）。重复/倒退不修改最后时间；向前缺口丢弃该块但移动时间锚点，下个连续块恢复。无自动回绕。
- 只在 `in_valid && in_ready` 消费输入；`feature_valid=0` 时拒绝，不学习、不触发、不产生结果。上游必须在未 ready 时保存输入，采集端不可回压时需独立 FIFO 并报告溢出。
- 每个接受的连续有效块生成一条 summary，包括 disabled/learning 块。`out_valid && !out_ready` 时所有输出载荷保持，且 `in_ready=0`，内部计数不前进。输出没有无界队列，不会静默覆盖。配置提交独立于输出，旧待取 summary 保持不变。
- `out_started/out_ended/out_active` 是 summary 载荷，只在输出握手时消费，不能当作独立每周期脉冲。`out_reason[0/1/2]` 为总能量上升/所选频带上升/总能量下降；其余位零。`out_band_mask` 标出触发频带。reason 是本块比较结果，不保证每个非零 reason 都开始新事件；学习/禁用块 reason 为零。
- `learned/background_power/background_bands/sticky_fault/config_generation` 是实时状态。`out_config_generation` 是对应 summary 生成时锁存的配置代号；阻塞期间配置改变不会混淆旧结果。summary 携带时间、原因、频带及活动状态，可交给未来事件缓冲器；当前没有缓冲器实例或完整事件元数据包。

## 配置原子提交

`cfg_data[191:0]` 必须在 `cfg_commit=1` 的上升沿稳定；同拍不接受输入。提交无效则旧配置完整保留且 fault[0] 置位。提交有效后取消内部活动/释放/冷却计数，但不改待取输出；这不是正常 out_ended 事件。使用方必须把配置代号变更视为取消旧 epoch，并先完成旧事件收尾。每次合法提交递增 32 位 config_generation，达到全 1 后拒绝继续提交直到复位，避免代号回绕。默认复位禁用；复位是清除 sticky fault 与时间锚点的方式。relearn 保留时间锚点；更改 block_samples 而不复位时，下块必须按新间隔连续，否则报告缺口。新采集会话或样本时间重新从零开始必须复位，不能只用 relearn。

| 位 | 含义与约束 |
|---|---|
|0|enable，0 时不学习、不开始事件|
|1|relearn，提交时清空参考并重新学习；是提交动作，不是持续电平学习。即使锁定也允许显式重学|
|2|lock，已学习参考禁止可选背景适应|
|3|adapt，完成学习后，仅无活动、无变化且无冷却时进行背景适应|
|7:4|保留，必须 0|
|15:8|八频带掩码；0 合法，此时只有总能量上升/下降检测|
|31:16|总功率上升比例 Q8，必须 >256。1024 对应功率 4 倍，约 6.02 dB|
|47:32|频带上升比例 Q8，必须 >256。没有 log 运算|
|63:48|总功率下降比例 Q8，必须 <256。64 对应低于或等于参考的 1/4；0 仅检测严格零输入|
|79:64|学习块数，1…65535；首块精确种子，之后 IIR 更新，不是算术平均|
|95:80|连续无变化释放块数，1…65535|
|111:96|单事件最大块数，1…65535，包含触发块；达到上限结束，绝不隐式重设背景|
|127:112|冷却块数，0…65535；结束后忽略恰好此数量的有效块触发|
|159:128|非零功率地板；上升要求当前功率达到地板，下降要求参考达到地板|
|163:160|IIR shift，1…15；ref +=/- abs(current-ref) >> shift|
|175:164|保留，必须 0|
|191:176|期望样本间隔，1…65535；参考流设 1024|

比较通过 56 位无符号扩展乘法实现 `current*256 >= reference*Q8`，下降为 `<=`。不对零参考除法，不使用浮点、dB 或对数。所选任一频带上升即可触发；这是明确的硬件简化，没有复现旧软件的 novelty_fraction 和 on/off dB 迟滞。释放计数提供时间迟滞。不能将有限 RTL 测试等同于旧软件召回率或逐位等价证明。

连续变化在同一活动事件内合并；短暂恢复未达到释放块数时再次变化仍是同一事件。结束进入冷却；持续异常在冷却结束后可再次触发。最大事件时长、禁用和提交不会自动吸收异常到锁定参考。锁定后只有显式 relearn 或复位改变参考。功率下降仅代表当前块相对参考的能量下降，不是周期节律或漏脉冲识别。断流不会被虚构成一条正常功率下降事件：报告数据缺口 fault 并终止内部活动。

## Sticky 状态与测试证据

fault[0] 配置非法；[1] feature_valid=0；[2] 时间重复/倒退；[3] 向前帧缺口/不允许的回绕。其余位保留 0。正常 ready/valid 背压不是错误。故障保持至复位；上位服务应同时读取 fault，不能只看 out_reason。

`tb_event_power_detector.sv` 在 Vivado 2025.2 的 xvlog/xelab/xsim 实际运行。日志为 `xvlog.log`、`xelab.log`、`xsim.log`。最后记录 PASS checks=36, starts=3, sticky_fault=0f。包含稳定背景后上升、等总功率频带替换、下降/中断、最大时长锁定参考保持、禁用、频带掩码、结果停顿、阻塞旧结果时配置代号保持、无效特征、前向缺口、重复时间、非法配置原子拒绝、重学及可选适应。有限定向测试，不是穷举或硬件时序证明。本目录不运行综合，由主任务统一执行。

复现（PowerShell，工作目录为本目录）：

```powershell
& D:/2025.2/Vivado/bin/xvlog.bat --sv event_power_detector.sv tb_event_power_detector.sv
if ($LASTEXITCODE -ne 0) { throw 'compile failed' }
& D:/2025.2/Vivado/bin/xelab.bat tb_event_power_detector -s event_detector_sim
if ($LASTEXITCODE -ne 0) { throw 'elaborate failed' }
& D:/2025.2/Vivado/bin/xsim.bat event_detector_sim -runall
if (!(Select-String -LiteralPath xsim.log -Pattern 'PASS event_power_detector checks=36 starts=3 sticky_fault=0f' -Quiet)) { throw 'simulation PASS marker missing' }
```

注意 xsim 遇到 testbench fatal 仍可能进程返回 0，必须检查 PASS 标记及 Fatal，不能只依赖进程返回值。
