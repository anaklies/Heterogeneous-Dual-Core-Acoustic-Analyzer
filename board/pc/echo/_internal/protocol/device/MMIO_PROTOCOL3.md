# 硬件 MMIO 协议 3（板级 HOST 接口）参考

本文件是**读自真实 RTL 的接口记录**，供 PS 网关把板级寄存器映射为 sixmic-analysis v1
网络能力使用。它不是 Windows 可以直接访问的地址：PC 不得直接访问物理 DDR 或 MMIO，
只能经 PS 网关。

来源（只读，不得修改）：
- integration/control/runtime_control.sv
- integration/instrument_top.sv
- integration/host/sixmic_host.h、sixmic_host.c、service_result.c、profile_upload.c
- integration/services/deployment_profiles.py、profiles/default/PROFILE.json

## 0. 访问规则

- 所有寄存器访问由一个 PS 控制端串行执行；PC 通过 PS 服务间接访问，不并发写配置。
- 基址候选：0x43C20000，窗口 4 KiB（instrument_top 的 host_awaddr 为 12 位字节地址）。
  必须以**最终 XSA/设备树**确认；当前不能宣称已映射为某个 /dev/uioN。
- 读写必须走 UIO/DMA 驱动或经确认的设备映射；普通缓存指针不能代替设备寄存器。
  volatile、Qt 信号、网络 ACK 都不是 DMA 一致性保证；A9 需要真实 cache clean/invalidate
  与 DMB 屏障。
- PCI/DDR：配置里的地址/长度以**字节**为单位，arena_words、descriptor 索引以 **32-bit 字**
  为单位，不得混淆。
- 未确认 Linux 保留区/UIO 映射/缓存一致性前，不执行真实 DDR 上传，只保留文件/fixture 测试。

## 1. 寄存器表（相对 HOST 基址的字节偏移）

| 偏移 | 访问 | 含义 |
|---|---|---|
| 0x000 | R | magic = 0x534D4132（'SMA2'） |
| 0x004 | R | 协议版本 = 3 |
| 0x008 | R | 固件 ID = 0x82000001（instrument_top 常量） |
| 0x00C | R | capabilities[31:0] |
| 0x010 | R | capabilities[63:32] |
| 0x014 | R | live faults（当前故障位，W1C 于 0x024 bit2） |
| 0x018 | R | result epoch 计数（0 = 尚无结果；0xFFFFFFFF = 饱和，丢弃新结果并置 fault bit31） |
| 0x01C | R | active config version |
| 0x020 | R/W | 状态：bit0 pending、bit1 result_irq、bit2 cfg_irq；写 1 提交 32 字影子（doorbell，必须整字 st==0xF） |
| 0x024 | W | IRQ/故障清除（W1C）：bit0 result_irq、bit1 cfg_irq、bit2 faults |
| 0x028 | W | clip release doorbell：d[0]=1，d[1]=bank；仅当 clips[bank] 存在且 0x2C 写入的 id 匹配时接受 |
| 0x02C | W | clip release id 暂存（字节写使能合并） |
| 0x030 | R | clip valid mask（bit0=bank0, bit1=bank1） |
| 0x040..0x0BC | RW | 32 字配置影子（word 0..31） |
| 0x100..0x17C | R | 32 字结果快照（word 0..31） |
| 0x200..0x23C | R | clip bank0 的 16 个不可变描述字 |
| 0x240..0x27C | R | clip bank1 的 16 个不可变描述字 |

结果快照一致性：读 epoch(0x018) → 屏障 → 读 32 字 → 屏障 → 再读 epoch；两次 epoch 相等
才可用。返回的是最新快照，不是无限队列；必须检查 frame/session/config、覆盖与丢弃计数。
epoch=0 表示尚无结果；epoch 饱和（fault bit31）时不能依赖该 mailbox 获得新数据。

配置提交：先写完全部 32 个影子字（0x040..），屏障，再写 0x020=1 原子锁存；pending 时
新提交被拒绝。每个请求版本必须不同于 active 版本，否则无法区分“拒绝”和“旧成功”。
应用完成由 status bit2 + 0x01C active 版本确认；拒绝置 fault bit30，并保持 active 版本不变。

IRQ：irq = result_irq || cfg_irq || (faults!=0) || clip_mask!=0。W1C 只清软件锁存位；
持续故障会立即重新置位。

## 2. 配置字（32 字，word 索引）

| word | 名称 | 单位/说明 |
|---|---|---|
| 0 | session | PL 会话代号（非零） |
| 1 | config version | 唯一递增，≠ active |
| 2 | arena_base | 字节地址（分析 arena 基址） |
| 3 | arena_words | 32-bit 字数（整块 arena 长度） |
| 4 | reserved_low | 字节下界（保留区） |
| 5 | reserved_high | 字节上界 |
| 6 | P1 descriptor table | 字索引 |
| 7 | P2 descriptor table | 字索引 |
| 8 | flags | bit0 P1_ENABLE、bit1 P2_ENABLE、bit2 PAUSE_P1_WHEN_P2、bit3 RECORD_ENABLE |
| 9 | bank0 | 字节基址（4 KiB 对齐） |
| 10 | bank_bytes | 每个 ring bank 的字节数（>=16 MiB，2 的幂） |
| 11 | raw_low | 原始录音区域字节下界 |
| 12 | raw_high | 原始录音区域字节上界 |
| 13 | bank1 | 第二个 ring bank 字节基址（4 KiB 对齐） |
| 14 | event_arm | bit0 = 事件捕获使能（与 flags.bit3 共同决定 event_cfg） |
| 15 | P1 last index | bits3:0 最后一个 P1 服务索引（0=1 个，15=16 个） |
| 16..21 | event config | 192 bit（RTL active_cfg[512+:192]，见 event 模块定义） |
| 22..29 | band edges | 256 bit 频带边界（RTL active_cfg[704+:256]） |
| 30 | P1 stride words | 相邻 P1 描述符字距（0=默认 24576；至少 64 且 16 字对齐） |
| 31 | P2 oneshot | bit0 P2 一次性执行 |

RTL 额外合法性（instrument_top raw_legal）：当 flags.bit3 或 event_arm 或任一 lease 有效时，
bank_bytes 必须 >=16 MiB 且为 2 的幂，bank0/bank1 4 KiB 对齐，bank0/bank1 >= raw_low，
bank0+bank_bytes <= raw_high，bank1+bank_bytes <= raw_high，且 bank0/bank_bytes 区间与
arena 的 P0 区间不重叠。违反则整包拒绝（fault bit30），不产生部分应用。

P0/P1/P2 分区参考 deployment_profiles.py（当前候选，最终以硬件 metadata 为准）：
- arena 0x10000000 起、4194304 字（=16 MiB 字节）
- P0 保护区：524288 字（0x80000）起之前私有区；P1 描述符表在 524288；P2 表在 524800
- P1 服务基数 600000、步距 24576；跨谱服务 851968；P2 基 1048576
- 各服务区间不得重叠；P2 独占工作区；不能沿用历史测试脚本里互相重叠的默认 base

## 3. 结果字（32 字）

| word | 名称 | 编码/单位 |
|---|---|---|
| 0 | protocol | 3 |
| 1 | algorithm | 0x82000002（候选算法 ID；不等于 CNN V8） |
| 2 | frame | 帧号 |
| 3 | config | 执行配置版本 |
| 4 | session | 会话 |
| 5 | slot | 结果槽 |
| 6 | fft_base | FFT 槽基址（字索引） |
| 7 | cycles | 处理周期 |
| 8 | sample_low | 采样序号低字 |
| 9 | sample_high | 采样序号高字 |
| 10 | faults | 故障位（见 §5） |
| 11 | mic_status | 麦克风状态 |
| 12 | missed_windows | 丢失窗口计数 |
| 13 | dropped_samples | 丢弃样本计数 |
| 14 | background_done | 后台完成计数 |
| 15 | overwritten | 结果覆盖计数 |
| 16 | failed | 失败帧计数 |
| 17 | temperature_centi | 有符号摄氏×100（16-bit 符号扩展到 32） |
| 18 | humidity_raw | SHT 原始湿度码；**不是百分数** |
| 19 | pressure_pa | Pa |
| 20 | sound_speed_float | IEEE754 float32，m/s |
| 21 | sensor_valid | bit0 temp、bit1 pressure、bit2 pose、bit3 sound-speed model 有效；bits5:4 环境补偿模式 |
| 22 | roll_pitch | bits15:0 roll、bits31:16 pitch，原始 int16 编码 |
| 23 | yaw | 原始 int16 零扩展 |
| 24 | qx_qw | bits15:0 qw、bits31:16 qx，原始 int16 编码 |
| 25 | qz_qy | bits15:0 qy、bits31:16 qz，原始 int16 编码 |
| 26 | env_sequence | 环境采样序号 |
| 27 | pose_sequence | 姿态采样序号 |
| 28 | sensor_errors | bits15:0 sensor_error_count、bits23:16 sensor_faults[7:0]，bits31:24 为 0 |
| 29 | lost_events | 丢失事件计数 |
| 30 | handoff_drops | 交接丢弃计数 |
| 31 | sample_rate_float | IEEE754 float32，Hz（当前 0x473B89C6 = 48009.775390625） |

使用约束：
- 采样率取 word31 的 float32，不得硬编码 48000。
- 湿度原始码、IMU 原始 int16 比例/姿态约定未确认前标记 raw/unverified，不显示成实测值。
- 传感器有效位/故障/sequence 必须一起检查；回退值不得显示为实测。
- P0 结果字只说明 PL 计算；不得据此宣称所有高级服务已整机验收。

## 4. clip 邮箱（2 个 bank × 16 字）

| word | 名称 | 说明 |
|---|---|---|
| 0 | clip id | 释放匹配 ID |
| 1 | base | 本 clip 所在 bank 字节基址 |
| 2 | offset | clip 起始偏移（字节，相对 base） |
| 3 | frames | 记录的 32 字节条数 |
| 4 | first_low | 首个 sampleIndex 低字 |
| 5 | first_high | 高字 |
| 6 | last_low | 末个 sampleIndex 低字 |
| 7 | last_high | 高字 |
| 8 | incomplete | bit0 = 录制不完整 |
| 9 | session | 会话 |
| 10 | config | 配置版本 |
| 11 | reason | 事件原因原始位（bits15:0） |
| 12 | pre_q22 | 事件前 Q22 非负相对功率 |
| 13 | post_q22 | 事件后 Q22 相对功率 |
| 14 | delta_q22 | uint32 位模式，按有符号差值解释 |
| 15 | age_valid | bit0 摘要测量有效，bits31:1 采样点年龄 |

顺序（强制）：核对 valid mask + bank → 读 16 字 → 再核对 mask/id → 复制环形两段数据
（bank_bytes 环绕，最多两段）→ cache 处理并持久保存 → 才按匹配 ID+bank 写 release doorbell。
不得只清中断就认为录音区已释放。错误 ID 本地与 RTL 都拒绝。两个 bank 都占用时记录丢失
事件；不能永远占满两个 bank，也不能静默释放。

每条原始记录 32 字节：6 个小端 sign-extended 24-bit PCM（各存 int32，低 24 位有效，
bit31:23 为符号扩展），随后 uint64 sampleIndex（低字在前）。起始物理地址 =
clip.base + clip.offset，按 bank_bytes 环绕。读取 sampleIndex 检测断序；文件长度不等于
连续性。

默认事件窗口（前 2 秒 / 后 3 秒 / 最长 8 秒）来自固件，不在 PC 重新定义。incomplete、
缺样、摘要过期、无效温湿度/姿态等标志必须保存并上报。

## 5. 故障位（result word10 / 0x014）

| 位 | 含义 |
|---|---|
| 0..19 | 管线细分故障（RTL error_flags） |
| 20 | 事件记录器故障 |
| 21 | 丢失事件 |
| 22 | P1/P2 交接丢弃 |
| 23 | 传感器聚合故障（明细在 result word28 bits23:16） |
| 30 | 配置被拒（版本未应用） |
| 31 | epoch 饱和（结果 mailbox 不可再用） |

故障位不别名传感器明细。P1/P2 后台数学/描述符错误停用相应 P1/P2 并置 bit19，P0 继续；
AXI、超时、保护错误仍停机，不得假装已自动恢复。

## 6. 服务结果发布头（DDR，16 字）

sm_copy_service 读取的发布头布局（word 索引）：

| word | 字段 |
|---|---|
| 0 | magic = 0x52534C54（'TLSR' 字节序按 LE u32 读为 0x52534c54；实现必须与 RTL/服务程序一致） |
| 1 | commit sequence |
| 2 | session |
| 3 | config |
| 4 | generation |
| 5 | programVersion |
| 6 | sourceFrame |
| 7 | sampleIndex low |
| 8 | sampleIndex high |
| 9 | slot |
| 10 | length（有效输出字数） |
| 11 | descriptor |
| 12 | error（0=无错） |
| 13 | pc（诊断） |
| 14 | done（1=完成） |
| 15 | reserved |

读取一致性（integration/host/service_result.c 已实现）：invalidate 头 → 读头 → 校验
magic/session/config/error/done/length → invalidate+读数据 → 再 invalidate+读头，**完整
16 字比较**；变化则重试。只有 magic 有效、done==1、error==0 且 session/config 匹配才可用。
这是读取一致性，不是长期 DDR 租约。执行帧时间不一定是离线输入文件的采集时间；离线资料
另附原始 recordId 与 provenance，不能混为同一来源。

## 7. 能力位与真实缺口

- instrument_top 当前以默认参数例化 runtime_control，**CAPABILITIES=0**：64 位能力查询
  当前返回 0。因此 PS 网关不得凭“寄存器存在”声明能力；默认汇报
  livePcm=false、liveResults=false、serviceSnapshots=[]。
- raw ring 写入器存在不等于 live PCM SDK 可用：六通道原始 PCM 的 PS 可消费游标/租约、
  完整带宽与网络链路都未验收。默认 not_ready。
- profile_upload.c 已知审查问题（两遍读取期间文件变化可能绕过第二遍边界检查）未关闭前，
  上传/激活能力必须 not_ready；不得开放网络任意 profile 上传，不得在网关内 fork 不一致的
  PL 协议。
- 所有高级服务不等于已完成整机 RTL 验收；STIPA 是分阶段高成本实验功能。
- 板级 HOST 基址/中断号/UIO 节点必须按最终 XSA/设备树确认；本文件只记录候选。
