# 共享结构、基础数据链与统一调度收敛记录

日期：2026-10-23。沿用既有计划，本轮只实施tasks1–3的基础子系统，不恢复NN/自动DOA/XYZ，不烧录、不修改历史正式工程或PS/PC界面。

## 当前交付

- `analysis_runtime.sv`：真实生产HLS FFT、共享标量核、AXI活动监测与采集/调度器已连接，并完成同一设计的OOC综合。四个实际DDR主端留给后续板级互连。
- `audio_pipeline.sv`、`pcm_capture.sv`、`sample_cdc.sv`、`window_pool.sv`、`window_dma.sv`：I2S/跨域/样本序号/不可变窗口/平面DMA和原始PCM环连接。以合成串行波形驱动真实I2S RTL，不是实物麦克风录音。
- `analysis_scheduler.sv`：P0优先、P1周期、P2选定任务分片及暂停P1；上下文绑定、源槽租约、配置原子更新、错误计数、超时排空与恢复。配置恢复同周期不会误报已应用。
- `shared_backend/scalar_engine.cpp`：最多64指令的共享PL执行核，读保护实时源槽，程序/上下文/写结果位于私有区。`band_program.py`提供从实际FFT输出计算选定频带相对功率的PL微程序示例，Native C验证通过；不等于52项完整服务已移植。

## 本轮实际修复

1. 窗口RAM推断失败：初次48492 LUT且存储LUT超器件容量。标准同步RAM模板修复后映射到BRAM；不是降低位宽或删功能。
2. 复数数组初始化变成一帧额外FIFO零数据：真实FFT RTL在变换启动前死锁。改用显式2048深度流接口。
3. 非法复数输入中途退出会残留FIFO数据：改为整帧预验证，之后才装入流。输入在租约期间必须不可变。
4. 迟到ready可启动已经超时的未接受命令；手动resume未检查generation；后台读实时槽缺少保护/固定；窗口导出器故障不能恢复；恢复与配置竞态。均有对应最小或控制级回归。
5. 独立仿真目录遗漏Hann ROM文件曾产生Inf，未当作通过；入口现复制ROM并强制数值/非有限检查。RED日志保留。

## 有效证据及其层级

|证据|实际结果|不能据此宣称|
|---|---|---|
|I2S/CDC/不可变窗口/DMA RTL|12288字、768 burst通过；含背压和租约|真实麦克风已通过|
|同一PCM的六通道FFT/PSD/电平C黄金|43074项通过|整条RTL已联合连续运行|
|最终生产FFT RTL，非法复数帧后直接正常PCM，无复位|状态3正确拒绝；后续7179项零差异，最大绝对误差7.15256e-7|全部高级声学服务已完成|
|最终单通道FFT实际RTL周期，含测试AXI等待|205200周期；六通道串行推算1231200周期=24.624ms|真实板卡DDR最坏延迟已保证|
|共享标量Native C|15项数学/上下文及7项非法边界通过；频带微程序6片完成|共享标量全部指令已有RTL数值验收|
|短控制回归|101窗，49次发布，601个FFT作业，P1/P2分片、配置、暂停、背压/故障/恢复通过|连续完整PCM硬件已验证|
|实测预算控制仿真|12窗、72个FFT作业、6次发布；最大间隔4265800周期=85.316ms，约11.721Hz|完整子系统RTL/实物10Hz已验收|
|连接子系统OOC综合|22224 LUT/21070 FF/58 DSP/52 BRAM36等效；520控制集|最终整板资源和Slice装箱|
|综合时序/CDC|WNS+5.186ns、TNS0、WHS+0.157ns、THS0；CDC219端点Safe、Unsafe0/Unknown0|实现后时序、真实I/O及板级CDC已关闭|

控制预算使用每通道211285周期（高于最终205200实测）、背景单片40000周期、窗口导出100000周期。背景片40000是测试约束/准入预算，不是所有服务程序已测最坏值。12窗中慢消费者不ACK，11次未消费覆盖均有计数，不是假装永久保存全部结果。正常P0没有静默丢失或队列持续增长。原始PCM录音环与谱快照的所有权不同。

## 当前节拍

之前512hop要每10.664ms完成六通道FFT，而实测基础计算就需要约24.624ms，不能持续。当前采用2048点无重叠窗口（约42.658ms），每两窗发布一次（约85.316ms）。保留连续原始采集，不改变FFT长度、数值缩放和频率分辨率。短暂事件独立特征通路仍归任务5，未冒充已实现。

## 不能提前关闭的门槛

这三部分的代码连接和分层验证已经落地，但既有计划的全部Gate没有强行标PASS：完整连续PCM→两实际HLS核→发布仍缺联合RTL证据；后台服务的最坏周期/全部功能程序、事件留证、传感器/PS寄存器映射和整板布局布线尚待后续任务。不生成Bitstream、不将`s7Complete`/`allAlgorithmsPorted`/`readyToFlash`设true。算法清单52条的逐项真实状态见FUNCTION_EXECUTION_MAP.csv。

## 复现入口

- 生产核心：`shared_backend/stream.cfg`、`scalar.cfg`，用Vitis2025.2 `v++ -c --mode hls --config ... --work_dir tmp/p20_stream_fft或p20_scalar`。
- 原生产FFT最小RTL测试：`tests/run_direct_fft.ps1`；要求上述导出存在。它直接使用生产RTL/XCI仿真包装，不使用被拒绝的cycle_probe计算RTL，仿真文件初始化及数值检查不可省略。
- 标量数学：`tests/check_scalar.py`；选带微程序：`tests/check_band_program.py`（先有FFT RTL实际输出）。
- 控制：`tests/tb_scheduler.sv`、`tb_scheduler_timing.sv`；接口：`tb_stream_job_bridge.sv`；DMA恢复：`tb_window_recovery.sv`。用Vivado xvlog/xelab/xsim，必须检查PASS且无Fatal，不能只看退出码。
- 组合综合：`build_runtime.tcl`，生成`tmp/p20_runtime_synth/runtime_synth.dcp`。这里只综合，不布局布线/烧录。
- 旧大分支hierarchy试验和UVM初始化试验均未批准采用；失败日志留存，不算PASS，不需要再跑。

具体数据布局、单位、租约和恢复条件见DATA_AND_SCHEDULING.md。独立GPT子代理审查及修复闭合见results/REVIEW_FIX_CLOSURE.md；本轮没有调用DeepSeek，未声称双模型验收。历史190/620未重新扫描；本轮仅对候选源码、证据及直接依赖生成独立SHA256清单。


## 2026-10-24 最终工程候选交付（本节取代上面的待构建状态）

已从完成的综合结果继续实际整板布线，未重复数值/逐帧PCM长测试。生成同版Bitstream、XSA、Vivado可恢复工程及routed.dcp：
`deployment/releases/SixMic3D_PL_Analysis_RC1_20261024`。

- 版本0x82000001，主协议3，CAPABILITIES=3；CUR1 +0x300，FFT四槽只读头 +0x400；ARM调用库包含五个当前接口模块。
- 同一个完整布线设计：40137 LUT(75.45%)、42117 FF、13114 Slice(98.60%)、88 DSP、57.5 BRAM36等价。WNS +0.149ns、TNS0、WHS +0.036ns、THS0；DRC Error0；CDC955安全、Unsafe0、Unknown0。方法学告警保留。
- 相对前一完整布线版本，减少2892 LUT、4340 FF、142 Slice；没有降低数学精度。Slice仍紧，不再为微小面积收益重构。
- 共享总线保守调度模型：6窗/3次发布、36个FFT作业，最长发布间隔4265800个50MHz周期，约11.721Hz。FFT/标量核、事件闭环、传感器失联、槽头与原音游标沿用有效最小RTL证据。
- 实际源码与恢复归档19项关键硬件文件一致，XSA内嵌bit与独立bit相同；归档校验及最终SHA256清单保存在交付目录。
- 完整15s STIPA 101阶段Native数值已通过(0.500005对参考约0.5)，不代表完整PL耗时通过；只保留慢速实验功能。

未强行关闭：8输入/8输出的外部电气延时边界，真实连续全链/板卡长期运行、实物传感器/LCD/看门狗、Linux保留DDR及2023.1 BSP与2025.2 XSA兼容性。没有修改0A或历史冻结，没有生成假BOOT/SD镜像，没有烧录。s7Complete保持false。

当前完成的是PL工程候选与调用材料交付，不是实物产品验收。函数清单分别保留程序验证、实际RTL、布线和物理测试状态；完整服务最坏耗时尚未逐项证明，不以本次封包伪造通过。
