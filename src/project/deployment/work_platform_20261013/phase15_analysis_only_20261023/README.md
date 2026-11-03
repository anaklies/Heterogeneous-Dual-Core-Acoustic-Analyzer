# 取消自动定位后的PL分析仪候选

日期：2026-10-23。用户取消NN与自动DOA，其余分析功能目标保留。
本目录是现有工程的独立候选续作，不覆盖原0A、旧PL/PS、Bitstream、XSA、
BOOT及历史归档。没有烧录，没有把C模型或HLS导出当作整机验收。

## 已落实的改动

- 新BD不实例化NN、DOA解码或网络1536点特征前端，不保留原14SI×5MI
  混合互连。PS7/MIO、HDMI和PS SPI0/EMIO配置继承原板级副本。
- 新共享2048点FFT/IFFT：去均值实数Hann、复数前向/逆向、六通道交织
  signed24输入，输出规范化FS复谱；逆向除2048。
- 原共享分析13项公式保持，新增峰保持、频漂、谐波带积分、IR反向积分、
  清晰度、衰减拟合、自相关基频候选7个阶段。不能计作7个完整用户服务。
- 新事件RTL：用户启停、学习/锁定/重学、可选适应、8带选择、能量突增/
  下降、持续事件合并与时限、配置代号、背压及时间异常拒绝。
- PS/PC接口保留主邮箱0x43C20000，分析核0x44A30000、FFT0x44A40000。
  参数偏移来自真实HLS头。分析任务适配器拒绝旧NN地址，DMA排空后读取
  HLS状态寄存器，避免拆分互连后错误地通过JOB读取DDR。
- GIF转换为320×172 RGB565，42帧、4.2秒循环；提供ARM Linux播放器和
  可选启动服务，厂商初始化复用。只验证转换/ARM编译/QEMU解析，未实屏测试。

## 受影响验证

|验证|实际证据|
|---|---|
|FFT厂商C模型|20480个实虚值，5种输入/方向场景，3个非法描述符；results/fft_csim_detrend.log|
|六通道数值连接|PCM24→FFT→PSD→频带，6不同音调/DC偏置，24检查；results/kernel_connection.log|
|新增数学阶段|11组/13275数值，7个非法/别名及1个无效拟合检查；results/extended_math.json|
|共享DDR C模型|峰保持/积分/拟合/地址别名拒绝；results/analysis_csim_review_fixed.log|
|事件状态机RTL|36检查，3触发；event/xsim.log|
|新命令适配器RTL|249检查，3真实启动；tests/bridge_sim.log|
|接口编码|64bit样本号往返、7项拒绝；results/interfaces.json|
|LCD|42帧/全部像素摘要、ARM编译/QEMU及4个错误包；lcd/verification.json|

没有重复旧房间、旧620哈希、旧评分黄金、完整PCM逐帧长RTL或旧整板布线。
新共享核与改变的互连各做必要的新综合，未为了小面积收益反复调参。

## 已修复的实际Bug

1. 新IR积分若从大总能量逐项相减，float32会丢失安静尾部。改反向累加，
   与独立双精度反向能量参考对照。
2. 新清晰度若用总能量减早期能量，80dB弱晚期成分消失。独立累加早晚区间，
   静态独立审查和最小数值重现后修复。
3. 共享分析核原来只检查各区域长度，没有在实际命令入口拒绝输入/输出重叠。
   已加操作级长度与区间检查，C原生及厂商burst模型均有拒绝回归。
4. 拆分互连以后旧命令桥的DDR metadata路径不再可达。新适配器强制使用
   HLS状态寄存器，并拒绝旧定位地址/错误参数数目和顺序。

独立GPT审查及修复闭合见results/INDEPENDENT_REVIEW.md。一次有限DeepSeek
事件审查返回incomplete且没有可用文字，保存原始证据，没有重试或声称通过。

## 资源和性能的准确口径

第一组合真实综合49334/53200 LUT、48618 FF、89/220 DSP、23/140 BRAM36等效，
零未解析黑盒，仍为抽象内部接口顶层，不是最终物理顶层。
相比旧86500 LUT设计，功能范围也取消了定位，不能称同功能压缩率。
分层发现分析核25498 LUT，级联数据互连仍数千LUT，因此进行一次单数据
SmartConnect结构比较，保持算法IP完全不变。最终选择及数字见ACCEPTANCE.json。

基础组合综合时序WNS=-1.820ns、WHS=-2.818ns，主要最差路径在旧异步
转换器边界；50MHz计算域自身报告setup+0.923ns。都不是布线后时序，不能
宣布关闭。无输入/输出delay约束994/645项含大量内部开发接口，不能接物理插针。

FFT内部transform的HLS固定调度15539周期（50MHz约0.311ms）；整个DDR封装
和分析核仍有不定访存延迟。不能用内部FFT数字冒充RTL实测或整机10Hz。
六路/512hop需要每秒562.5次FFT，内部核预算约17.5%计算时钟，不含DDR、
去均值、功率/互谱、高级任务及争用。当前每通道跨步读取重复取入交织缓存行，
访存请求延迟和带宽应优先做真实调度验证，而非假定理论DDR带宽足够。

采用厂商有文档的方法：
- SmartConnect纯AXI-Lite控制端可使用低面积模式：
  https://docs.amd.com/r/en-US/pg247-smartconnect/AXI4-Lite-Low-Area-Mode
- FFT Burst架构用顺序共享换取面积，不假装能任意重叠帧：
  https://docs.amd.com/r/en-US/pg109-xfft/Burst-I/O-Architectures

## 尚未完成，不得遗漏

- 51个有效技术登记条目不是51个独立功能；完整审计见interfaces/FUNCTION_PORT_AUDIT.csv。
  频率计权/统计、Zoom、边带、互相关/GCC、倒谱、空间峰、相对隔声、STIPA、
  NC/NR、分频衰减等完整PL服务仍未闭合；公共原语不能冒充这些服务已部署。
- 真实I2S采集→不可变窗口→FFT/分析的物理连接、全局缓冲所有权与帧界调度。
- 事件前后录音保留/复制、完整前后差异摘要、用户任意Hz频带配置链及真实上报。
  新事件核的8带索引选择不能当成任意Hz接口；功率下降不等于周期漏脉冲检测。
  新RTL有意采用功率比简化判断，不借用旧软件30TP/6FN作为其性能成绩。
- 新命令桥与各目标DMA监测实际连接、PS和PL单一控制所有者、真实共同复位。
- 原SHT30/IMU局部模块复用但未接入当前物理顶层，也未做实物传感器检测。
- 新整机连续吞吐、布局布线、Slice装箱、外部约束、CDC/DRC、功耗及匹配Linux启动。

actualHardwareCapabilityMask=0、algorithmVersion=0、readyToFlash=false。
没有生成新Bitstream、XSA或启动包；没有QSPI/eMMC擦写。

## 本轮最终选择

选择一次结构对照后的紧凑数据互连候选，计算核/数学公式不变：

|组合综合|首个分析仪候选|紧凑互连候选|
|---|---:|---:|
|LUT|49334，92.73%|45296，85.14%|
|FF|48618|44012|
|DSP|89|89|
|BRAM36等效|23|23|
|Unique control sets|1779|1424|

单次同算法结构优化节省4038 LUT及4606 FF，未再追逐少量LUT。
保留首候选检查点用于回退；新候选为tmp/p19_compact_data/compact_analysis_synth.dcp。
两者都零未解析黑盒，不包含全部未接入的功能/调度/传感器等逻辑，不能按此
保证全集最终面积。没有已放置Slice数量，不能用LUT余量替代装箱证明。

紧凑候选综合WNS=+0.923ns、TNS=0；WHS=-3.255ns、THS=-715.488ns。
保持时序未闭合，尚未布局布线，仍不能发布。BD内部AXI和事件调试端口
是内部连接边界，不是物理插针。309条综合警告/0 critical/0 errors为本次
运行末尾计数，不表示全系统没有Bug或所有约束通过。

两套HLS导出与最终DCP、源头依赖哈希见SOURCE_REFERENCES.json；本目录
源码/证据清单见SHA256SUMS.txt。最终已验范围、剩余项见ACCEPTANCE.json。

## 复现入口

使用已有Python环境phase12h_srp_dnn_salsa_20261020/.venv/Scripts/python.exe。
新增数学：tests/check_extended.py；接口：interfaces/build_contract.py后
tests/check_interfaces.py。已通过且代码不变时不要重复执行。

厂商C模型：Vitis2025.2 vitis-run --mode hls --csim --config fft/csim.cfg，
analysis/csim.cfg或tests/connection.cfg，分别使用独立tmp目录。
HLS导出：v++ -c --mode hls --config fft/fft.cfg或analysis/analysis.cfg。
首组合构建：board/build_analysis_board.tcl；单数据互连比较：
board/compact_data_fabric.tcl。后者继承前者已验证的BD，不重训、不改算法。

LCD运行条件及安装位置见lcd/README.md；服务文件没有在任何系统上启用。
