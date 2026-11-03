# PS/PC 底层 HOST 协议 3（开发候选）

这是可移植 C99 访问层，不包含定位或 DSP 运算，不是 UI，也不是已上板驱动。真实板卡、传感器、Linux 映射和网络传输均 **NOT TESTED**。当前能力位默认为 0；寄存器和软件测试存在不代表所有算法已验收。

## 接入和同步

`sm_device` 由调用者提供 32-bit MMIO 读写及设备屏障回调。地址是相对 HOST 基址的字节偏移；当前板级草稿基址为 `0x43c20000`，必须以最终 XSA/设备树核对。读写回调需返回实际访问失败，不能吞掉 AXI SLVERR。PS/Linux 应使用驱动或经过确认的设备映射和 ARM 屏障；普通缓存内存指针不能代替设备寄存器。

所有操作由一个控制端串行执行。PC 通过 PS 服务调用这些 API，不直接同时改写设备。提交配置前写完全部 32 个影子字；最后 doorbell 原子锁存，pending 时拒绝新提交。每次使用不同于当前 active_config 的版本号，避免拒绝后仍被旧版本误判为成功。`sm_config_status` 单次查询，不在实时线程忙等；完成后可 W1C 清 cfg IRQ。IRQ 位分别为结果、配置、故障，写 1 清除；持续故障可能立即重新置位。

结果读取采用 epoch—32 个数据字—epoch，比对失败重试。epoch=0 尚无结果；若计数饱和（故障 bit31），不能依赖该 mailbox 获得新数据，应停止本会话并处理恢复。返回的结果是最新快照，不是无限队列；检查 frame、session、config、覆盖和丢弃计数。所有 64-bit sample index 为低字在前，以帧内携带的 float32 实际采样率换算秒；不是 Unix 时间。

## DDR 与缓存

需要在 Linux reserved-memory/专用 DMA 分配中保留整个分析 arena 及两个原始录音 ring，不能使用 Linux 普通堆或允许页面换出的内存。配置内 DDR 地址、长度、上下界以**字节**计；arena_words、程序/描述符/上下文索引以 **32-bit 字**计。不得和内核、显示 framebuffer、FSBL 或其他 DMA 缓冲重叠。当前 root 对录音 ring 另有最小容量、对齐和不重叠检查。

程序/参数上传完成后，执行针对 DMA 的 cache clean 和写屏障，之后才提交配置；PL 持有的程序与输入不能被改写。读取 DDR 前等待硬件完成/有效包，按平台执行 invalidate 或使用真正一致的映射。HOST 回调的设备屏障不等于 DDR cache 维护。`sm_read_snapshot` 只能保证寄存器包一致，**不能授予 FFT 槽永久租约**；实时 FFT 槽会重用，读取完整 FFT 必须额外检查帧代次或采用后续明确的复制接口。不要把寄存器 epoch 当作防覆盖 DDR 锁。

## 事件双 bank 和数据格式

`sm_read_clip(bank)` 仅在 valid mask 有效时读取 16 个不可变字，再核对 ID/mask。每个 clip 的环形数据有实际租约，直到 `sm_release_clip` 写匹配 ID + bank doorbell。先完整复制数据并完成缓存处理，再释放；释放后该 DDR 可立刻被采集覆盖。两个 bank 均被占用时会记录丢失事件，不承诺无限录音。`incomplete` 不为 0 时必须展示丢失/不完整标记。

每条原始记录 **32 字节**：六个小端 sign-extended 24-bit PCM（各存于 int32），后接 uint64 sample index，低字在前。起始物理地址为 clip.base + clip.offset；frames 条记录以 bank_bytes 环绕，最多拆为两段复制。读取 sample index 可检测断序；不能将文件长度等同于连续性。归一化到 FS 是后续分析运算，原始保存保持位模式。

clip word 12/13 为 Q22 非负相对功率，word14 为 uint32 差值位模式（需要按有符号差值解释），word15 bit0 为摘要测量有效，bits31:1 为采样点年龄。reason/mask 为 word11 的原始字段，使用对应冻结事件算法的定义；不要编造声源类别。

结果 word17 为有符号摄氏度×100；word18 是 SHT 原始湿度码（不是百分数）；word19 为 Pa；word20 和 word31 是 IEEE754 float32 m/s、Hz。word21 bits0..3 为温度/压力/姿态/声速模型完成有效，bits5:4 为环境补偿模式；检查传感器故障和 sequence，不能将回退值显示为实测。姿态角及四元数保留传感器驱动的原始 int16 编码，应用必须核对实际 IMU 型号/比例，不能仅凭字段名假定单位。未验证物理传感器。

## 复现（仅本地 fake-MMIO）

在此目录运行：

```powershell
D:/mingw64/bin/gcc.exe -std=c99 -O2 -Wall -Wextra -Werror sixmic_host.c test_sixmic_host.c -o test_sixmic_host.exe
./test_sixmic_host.exe
```

实际结果：`HOST_API_PASS protocol=3 snapshot_retry config32 clip2 ID_release IO_errors`。覆盖版本拒绝、结果更新重试、32 字原子提交、pending 拒绝、配置完成、两个 clip、错误 ID 拒绝、释放及回调失败。它是 C API 模型测试，不冒充 RTL/AXI 联合或板卡验收。

P1硬件轮询：配置word15低4位为最后一个服务索引（0=一个，15=16个），word30为相邻描述符的字间距（0默认24576，至少64且16字对齐）。每个服务有4槽描述符族，指令/历史必须互不重叠；完成后PL递增索引并周期调度，不把同一frame计作新观察。后台数学或描述符错误停用相应P1/P2并置fault bit19，P0继续；AXI、超时、保护错误仍停机，不假装已经自动恢复。

## 可选系统看门狗（未安装、未实机启用）
`sixmic_supervisor.c` 只管理系统：实际观察到 PL 帧推进后才打开硬件看门狗，基础链停滞2秒或发生基础总线/调度故障后停止喂狗，依赖真实 PS 硬件看门狗执行整机复位。传感器失效、安静/常数麦克风、后台数值错误和事件丢失只报告，不制造反复重启。`common_bus_reset_ack` 仍接0，不能假装本地已经排空故障总线。

`build_arm.py` 复用既有 sysroot，已经生成 `sixmic-supervisor-arm`（仅 ARM 编译）；`test_watchdog_policy.c` 为纯策略测试。还没有核对目标 Linux 的 UIO映射、watchdog节点、nowayout/魔术关闭、PS/PL共同复位及启动文件，不能直接把编译通过当成整机重启验收。请勿在主机PC执行或在未匹配BSP时启用它。正式启动服务仍待板级集成。

## 2026-10-24 接口收口补充（以本节和当前头文件为准）

### 连续原音游标（新增，可选扩展）

硬件MMIO主协议仍为3。整板候选CAPABILITIES bit0表示存在CUR1只读游标区，地址HOST+0x300..0x33f；旧固件没有该能力，不得硬读后假装支持。

|word|含义|
|---|---|
|0|magic 0x43555231|
|1|当前raw bank generation|
|2/3|实际当前bank物理base / bytes|
|4|下一写入位置，字节偏移|
|5/6|本generation已成功提交的记录数，uint64低/高；不是sampleId|
|7/8|最后成功提交的sampleId，uint64低/高|
|9/10|raw丢失计数 / pipeline错误位|
|11/12|当前控制session / configVersion|
|13|配置采样率float32（不是时钟实测值）|
|14|记录格式1：六个sign-extended s24 LE32 + uint64 sampleId，共32bytes|
|15|bit0 configured，bit1 record armed，bit2 writer enabled，bit3/4 leased banks，bit5 64bit计数上限|

`raw_cursor.h/.c`提供双读一致游标和安全复制。按generation内的**记录序号**寻址，不能用sampleId差推算环中位置，因为采集中可能丢样。调用者将返回cursor.generation与自己跟踪的generation比较，换bank就记录gap/重新定位，不得拼到旧代次。

当前bank没有永久租约：即使AXI写响应还没回来，下一写入槽也可能正在覆盖旧数据。因此满环时故意排除最老一个槽；复制后再次确认代次、计数及是否覆盖。事件clip仍使用真正bank租约，两条路径不可混淆。双bank为“一边持续写、一边封存”，不是无限事件队列。

游标RTL计数、实际writer/recorder/邮箱联合、C环回绕/丢样/换代次/半写边界已测试；Linux映射、网络持续吞吐、实物采集尚未测试。开启livePCM前，后端还必须核对实际reserved-memory与驱动。

### 结果发布头与私有区

结果输出前16字为发布头；容量word10是**可写工作区容量**，不是所有字都是可展示结果。实际绘图/导出长度和字段类型以服务metadata为准，不能把系数、scratch和uint32计数全当float曲线。

复制结果前后比较完整发布头，包含源帧、源采样时间、session/config/generation、programVersion及descriptor；不能只比较某一slot的指令数。记录数据分析的执行帧不等于输入录音的采集时间，另保留recordId/原始采样序号。

共享核允许最大512条指令片段，普通服务默认64，STIPA长任务使用512。实际RTL普通512片段24889周期，STIPA内存密集片段29905周期（测试AXI等待），低于40000后台准入预算。这是实测代表负载，不是无限DDR阻塞的硬件上界。

指令累计计数0xffffffff后明确报错7，需要新generation；后台管理应在预算接近上限时于完整任务边界更新代号，保留或明确重置统计历史，不把预算用尽说成硬件死机。失败/半写数据不发布有效头。

### 功能可用性

- 精确FAST/SLOW新增`time_response_recorded`入口，对已确认连续的记录逐样本计算；稀疏实时窗口仍显式失效，不能宣传为持续精确时间计权。
- STIPA是实验、慢速、需已知参考/接收记录的101阶段程序；完整15s、101阶段Native程序图已完成：4,893,057片段，254.801秒CPU时间，指数0.500005对参考约0.5；这不是完整RTL/板卡耗时，不作为P0实时功能。阶段图/参数页由主机组织，所有声学运算仍在PL。
- 静音时FFT电平有效性字段为0，dBFS槽0仅占位；不能显示成“0dBFS满幅”，也不能把安静直接判为麦克风损坏。
- 房间指标需明确的IR/经用户选定起点的衰减录音；无绝对参考时不输出认证隔声、NC/NR或SPL。

### PS管理注意

UIO IRQ是电平触发，持续传感器故障会保持故障中断。不能反复清标志/立即重开IRQ造成中断风暴；应保持故障可见并退避轮询，确认实际源消失后再恢复中断。传感器未接、静音/常数通道及可选任务数值错误不应造成反复重启。

ARM调用库为`libsixmic_host_arm.a`；头文件支持C++的extern C。上传器已经改用有界不可变文件快照，并在实际写入再校验P0保护边界；中途文件变化回归通过。仍必须先禁用并排空P1/P2、核对真实DDR保留区，上传成功不等于已经激活新配置。

本轮没有安装系统服务、修改网卡、擦写启动分区、连接开发板或启用看门狗。PS网关和最终UI由后续软件工作接入。

### 实时FFT/电平读取：CAPABILITIES bit1与槽表

HOST+0x400..0x47f为四个只读槽头，每槽8字：ready、frameId、configVersion、session、firstSample低/高、FFT区相对arena的字节偏移、schema=1。ready在槽被下一窗口占用时先清零，在六通道FFT与该帧处理完成后置位。

必须使用`fft_snapshot.h/.c`：先读取原子结果邮箱确定帧/槽，再读取槽头并核对来源，复制后再次核对整个槽头。全局result epoch不变并不能证明FFT槽没有被改写，因为中间未发布窗口也会复用槽。没有bit1/槽表的旧固件不能安全地当作此接口使用。

`sm_copy_fft_snapshot`的memory.reserved_low必须是实际analysis arena base。每通道7179字，通道stride8192字；选中的通道按通道号升序打包。容量参数单位是32-bit字，不是字节。返回SM_RETRY/SM_NO_DATA时丢弃整份复制，不能把半帧发给PC。读取7171..7178可获得RMS、peak、peak-to-peak、mean、dBFS、crest、clipping和有效性；静音时不要将占位dBFS=0当作满幅。

### 配置切换的唯一推荐流程

1. PS仲裁器持有已确认的active配置，先提交一个**新版本**的配置，仅关闭P1/P2，保留正在进行的raw录制及其几何配置；等硬件实际applied。不能只在软件里设一个idle标志。
2. 使用对应最终版本号构建/装载私有程序镜像（所有4槽描述符的session/config/generation一致）。全SMI初始化会重置P1/P2统计，因此要把“统计已重新开始”告知前端，不冒充无缝累计。P0仍保持采集/FFT。验证DDR保留区后才能写入。
3. 再提交另一个唯一版本的最终配置，等待applied；只在实际生效后宣布功能启用。例：active V → quiesce V+1 → image expected V+2 → activate V+2。不要反复用工厂默认config=1。

只更改事件/录制配置也必须遵守描述符版本绑定；不能直接把active config更新后仍运行旧版本描述符。由于64条片段可中途取消，取消后不得继续使用部分统计历史当作完整历史；首版通过显式统计重置处理。

STIPA整个101阶段期间P1保持关闭，P0继续。阶段推进只写stage_patch返回的P2表/代码/上下文/配置权重/无效发布头，不清空PL已经产生的录音及中间数组。每阶段使用匹配的新config/generation；恢复P1前重新准备匹配的P1描述符，不能让旧config描述符自动运行。

背景完成总数不是某个具体任务的完成确认；按独立输出发布头的descriptor、programVersion、session/config/generation及done/error确认。初始接管不明配置、旧影子与active不一致时先保持只读，不猜测实际arena或raw几何。

### 首版测量含义

默认FAST/SLOW入口是连续录音的精确样本递归分析，需确认输入连续；一般live电平来自P0逐窗RMS/peak。A/C/Z为相对数字频域计权，不能称认证声级计。
异常检测当前作用于六通道总能量及所选频带，保留学习/锁定、变化/能量中断、预后原音和摘要。自动DOA已取消，因此不能宣传自动扇区归属/XYZ报警；复杂周期声节拍缺失也不是现有能量损失规则的保证能力。
