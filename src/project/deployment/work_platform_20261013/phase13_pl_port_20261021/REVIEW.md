# Phase13 控制与安全RTL独立审查

范围：analysis_axi_control、pcm_axi_ring_writer、mic_health、profile_scheduler、direction_pose_transform及对应Testbench。仅静态独立审查；未修改RTL，未运行大型仿真/综合。以下行号对应本次读取版本。

## 需要处理的三项

### 1. P1：持续故障会使IRQ无法在设备内屏蔽，存在Linux中断风暴风险

`rtl/control/analysis_axi_control.sv:45,63,85-88`：irq直接包含所有sticky_faults；任何live_fault持续为1时，写0x028清故障仍将sticky重新设成live_fault。设备没有IRQ mask/enable寄存器。若连接PS的电平中断并由常规ISR确认后返回，断开的传感器或持续采集故障可令中断立即重入，影响UI和网络响应。

这不是AXI握手错误；可通过驱动屏蔽整条IRQ并轮询规避，但需要明确集成契约。建议增加独立故障IRQ使能掩码，状态仍持续可读；或改成故障上升沿锁存并允许确认，而不是必须等物理故障消失。

最小测试：live_faults=0x10持续100周期，CPU确认后屏蔽该原因，IRQ应可撤销；状态0x020仍显示0x10；出现新未屏蔽故障可再次中断。现有测试只证明故障状态不会被误清，未覆盖CPU中断退出。

### 2. P1集成契约：DDR重配置后旧提交描述符仍指向上一环形区

`rtl/control/pcm_axi_ring_writer.sv:77-79,108-110`：接受新base/length时只重置next_write_offset，committed_samples与last_committed_sample_id保留旧值，而且没有ring/config generation输出。新环形区还没有任何有效样本时，读端能看到旧的非零提交数和旧sampleID，容易将旧区的进度解释为新区数据。

若预期committed_samples是生命周期计数，则并非必须清历史，但PS必须在每次成功配置后记录计数基线并等待新的提交。当前模块接口/测试没有把这个前提固定下来。建议增加ring_generation与本区valid_count，或明确重配置同时清本区提交描述符并保留独立生命周期统计。

最小测试：区A提交一条样本→停用/排空→配置区B→尚未输入样本，断言新区有效样本数为0且generation改变；首个B提交后才能读取B。当前TB只验证单一配置内的地址环绕。

### 3. P2：采集断流后健康统计窗口跨越缺口，恢复一条样本就可能发布“新窗口”

`rtl/control/mic_health.sv:53-69`：进入acquisition_stale时没有清window_count、changed、clipped、active和different_pair。若在一个窗口已有WINDOW_SAMPLES-1条样本时断流，恢复的第一条就会清acquisition_stale并发布window_valid；该记录实际上混合了断流前后数据。

建议在首次进入stale时丢弃未完成统计窗口，恢复后累积完整窗口再发布；或增加window_discontinuous标志，让上游不得把它当作连续新鲜健康证据。不要将此问题变成“静音=坏麦克风”。

最小测试：WINDOW_SAMPLES=8，先7条→空闲超过NO_SAMPLE_CYCLES→恢复1条，要求window_valid不应被当作完整连续窗口；再累积剩余7条后才有效。现有TB在完整窗口结束后才断流，因此没有覆盖。

## 已确认的正面设计

- AW/W独立捕获、B/R背压保持和WSTRB更新正确；未知/未对齐地址返回SLVERR。
- 配置shadow与待提交值分开，result_valid同时发布32字，epoch允许读端检测跨读覆盖。
- PCM写入单一8-beat burst，32字节样本/4KiB对齐，配置限制在声明保留区；B错误不计成功，丢失计数显式。
- AXI超时后保持在途VALID/数据，不随意抛弃已接受burst；这是正确的总线行为。恢复可能需要PS/互连级处理，不能承诺仅重启master就恢复。
- scheduler只发布匹配事务/版本结果，三次连续超时锁定，清计数不会擅自重新启动。
- capabilities由真实集成输入提供，缺失P0阻止启动；不能由软件功能目录直接生成全部通过位。
- 失效姿态回退为局部坐标，world_valid和heading_referenced分开；固定安装变换没有重复施加。
- 不足以判定硬件故障的安静/恒定/同值通道只作warning，未伪造“已证实坏麦克风”。

## 验收边界

本审查不证明实际I2C响应、PS DDR保留区/缓存一致性、CDC、HP端口连接、神经网络10Hz或整板时序。三个问题应通过对应最小测试处理；不需要重跑旧M/N完整声学数据或大型布局。
