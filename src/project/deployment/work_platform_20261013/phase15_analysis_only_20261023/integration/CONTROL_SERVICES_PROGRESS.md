# 剩余PL补齐：本轮实际状态

本轮尚未达到“只剩PS/PC软件”的交付条件。没有进行界面设计、烧录或旧工程覆盖。

## 实际新增

- `services/`：8组共享PL微程序构建器（复制/冻结、峰值保持、EMA、三点平滑、倍频程/1/3倍频程、频谱形状、通量/差异）。Python只生成指令和参数，实时数学在PL共享核中执行。父任务独立运行15项/7229值Native C–NumPy比对通过。不是RTL或整板验收。
- `scalar_engine.cpp`：FLOAD target2允许在受保护输出区读取历史，保留实时输入只读及代码/上下文保护。原15项及7项非法边界回归通过，新版HLS导出完成。HLS估计13622 LUT、7189 FF、27 DSP、4 BRAM18；这些不是整板综合数。
- `control/runtime_control.sv`：PS/PC共用的AXI-Lite控制协议，独立AW/W、字节写、配置影子/提交、busy拒绝、epoch结果快照、能力查询和中断。新增RTL短测试通过，包括配置完成与W1C同周期。能力默认0，不能把尚未接入的服务开放为已实现。
- `control/runtime_v2.h`：非阻塞C调用接口，无UI。主机模拟测试通过epoch重试/串行提交。A9 MMIO及DDR缓存维护条件写明，尚未在ARM/板卡运行。
- `control/event_recorder.sv`：双DDR环停写排空、合法重配置确认、旧bank租约、匹配ID释放、预后区间、合并上限和丢失计数。短RTL测试覆盖正常预后、排空额外尾段、预触发已丢样、环容量边界。缺口采用保守不完整标志，不能伪称完整录音。
- `control/instrument_sensors.sv`：复用已有真实I2C hub及声速模型，SHT低频采样、IMU姿态/气压、有效性/故障及声速模式接口。展开检查通过，尚未板级连接或电气测试。

## 仍未关闭的主要门槛

1. 这些服务尚未纳入完整服务选择/多阶段FFT-IFFT调度。CSD/相干、GCC、包络/倒谱、手动DAS、房间/STIPA等仍不能标记完整PL执行通过。逐项表已更新，未静默删功能。
2. 事件特征→检测核→双环控制→实际PCM写入器→PS异步保存尚未接成真实闭环。新录音控制模块通过不等于完整事件功能通过。
3. 传感器、控制寄存器及事件服务尚未纳入同一个物理顶层，尚无本轮整板布局布线/时序/10Hz证据。因此未运行无意义的“不完整整板验收”。
4. 旧22224-LUT/41.77%报告仅对应上轮子系统；本轮共享核修改、新服务和控制没有被该DCP包含，不能冒充当前整板资源。`currentSourceMatchesPriorDCP=false`。

## 审查

独立GPT审查提出预录缺口、尾段/环容量、W1C竞争问题；父任务修复并补明确短RTL用例通过。一次DeepSeek API审查返回incomplete且无正文，只保存诊断，不声称完成双模型验收。原审查文件中的未关闭描述应结合本次修复及`event_corner_final.log`、`control_corner_final.log`读取。

## 证据与入口

- `services/test_programs.py`、`services/NATIVE_RESULTS.json`、`services/service_bundle.json/bin`。
- `tests/event_corner_final.log`、`tests/control_corner_final.log`。
- `tests/test_runtime_api.cpp`；`tests/tb_runtime_control.sv`、`tests/tb_event_recorder.sv`。
- `results/scalar_history_hls.log`、`results/CONTROL_SERVICES_REVIEW.md`。
- `CONTROL_SERVICES_SHA256.json`及当前SOURCE_EVIDENCE_SHA256.json。原manifest另保留PRE_CONTROL_BASELINE_SHA256.json，历史190/620未重扫。

本轮状态继续为allAlgorithmsPorted=false、readyToFlash=false；不生成冒充全功能的Bitstream或启动包。

## 2026-10-24 收口继续：本轮实证与边界

- 未调用DeepSeek；不设计PS/PC界面、不写QSPI/eMMC、不连接或烧录实际板卡。
- 统一入口Native调用32个代表服务通过，追加FAST/SLOW默认映射到连续录音精确模式并通过；STIPA完整15秒双记录、101阶段Native已走通，结果0.500005与已知约0.5匹配，耗时254.8秒（CPU Native参考，非FPGA实测/非认证）。
- 最大片段上限由64扩到512，普通服务仍64。512普通片段实际RTL24889周期，内存密集STIPA片段29905周期，完整80字上下文匹配，低于40000后台预算。
- 有效复数FFT→IFFT真实RTL8192字验证通过（265724周期）；继承原六通道PCM/FFT数值及串行采样证据，不重复运行长PCM数学仿真。
- 真实features/detector/raw writer/recorder/mailbox联合RTL及11个实际截取样本的6通道值/采样序号/WAV24 roundtrip通过。测试缩短PRE/POST为4/6样本，不冒充实物默认2/3秒录音测试。
- 上传器改用不可变有界快照，中途改文件不能越过P0保护区；Native回归通过。公开C接口支持C++并生成Cortex-A9静态库。
- 新CUR1游标和C复制接口处理64位记录计数、换bank、环回绕、sampleId缺口；故意排除正在覆盖的下一写槽。
- 最后核对发现P0 FFT槽缺少公开有效性，补0x400四槽头及C快照复制保护。RTL/host模型已通过“占用即失效”和“全局epoch不变仍拒绝混帧”；最新整板必须包含此增量。
- CE控制集重映射已实测无面积收益（LUT43275/Slice13264较旧43029/13256更差），拒绝并停止进一步同类搜索。
- 采用AMD共享访问低面积AXI互连候选，DDR数据面保持PS HP1/既有宽度，不改采样率/算法数值；此前预槽表综合42384LUT/43551FF/88DSP/57.5BRAM等效，尚不是最新含槽表的最终物理报告。
- 最终构建正在收口；不得把旧80.88%/99.67%报告当新源码数据。完整RTL连续PCM/实物采集/实际Linux驱动/网络/看门狗复位/LCD点亮仍非已验证项目。
- STIPA等高成本实验程序虽有完整可执行图，PL端总体时长尚未实测，通用解释核可能造成分钟到小时量级风险，不能宣传实时STIPA。房间/隔声/NCNR需要有效输入/参考，数据与测量含义分开。
- 三步配置流程及统计重置/STIPA全图P1关闭已写入host/README末节，避免描述符旧版本或部分历史被当作完整状态。
