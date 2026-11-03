# PL/PS/PC调用边界 v1

FUNCTION_REGISTRY.json登记52项软件功能/功能组，不是52个硬件核。P0=10，P1=17，P2=25。
真实implemented_mask由已集成并通过的RTL提供；本开发阶段不能从登记表自动填满。缺P0时拒绝启动。算法版本寄存器由实际后端输入，无后端为0，不用软件版本常量伪装已部署。

AXI-Lite寄存器与Phase13 analysis_axi_control一致：

|偏移|含义|
|---|---|
|0/4/8|Magic534d4131 / ABI00010000 / 实际算法版本|
|10/14|真实硬件能力64bit|
|18/1c|缺失P0位|
|20/24|故障状态 / 原子结果epoch|
|28|读通知：result,cfg_applied,cfg_error,fault_pending；写1确认结果、bit1确认配置、bit2确认故障通知|
|2c|bit0清故障重试锁，bit1清计数；两者独立|
|30/34/38/3c|生效配置版本/请求ID/超时数/采样丢失数|
|40..64|待提交requestID、PS-P1、PC-P1、PS-P2、PC-P2掩码、暂停无关P1|
|68|写bit0提交不可变配置；在下一帧边界应用|
|70|中断掩码：bit0结果、bit1配置、bit2故障；复位默认屏蔽|
|100..17c|32word原子结果，读epoch前后相同才接受|

以上偏移均十六进制。多个PS/PC客户端必须经过一个控制服务串行化shadowwrites；退出PC页面不得删除PS仍订阅的功能。C客户端为可复用访问层，不含UI、网络驱动或DSP。

结果32word的具体kind决定布局；统一前10word约定magic、ABI、真实算法版本、kind、frameId、configVersion、sampleId低/高、processingCycles、errorFlags。其余内容按kind/validity定义，未产生的算法不得发布假结果。大频谱/IR/音频走带版本和样本范围的DDR块描述符，不塞进128byte邮箱。

PCM DDRwriter每sample32byte：6个signed32 signextendedPCM24，sampleID低32、高32。4KiB对齐保留区；每次重配置region_generation递增，本区committed_samples/lastID清零；PS按next_write_offset和min(committed,bytes/32)读环。序号跳变必须上报，不能把缺失样本拼成连续录音。

DDR地址仅能来自Linux reserved-memory或DMA分配且正确同步的区域，不能把普通malloc虚拟地址写进PL。缓存一致性/AXI HP接线尚未实机验证。PS网口优先用于PC，PS仅解码、存储、通信；不承担本项目核心实时声学算法。

时间以sampleID为准，UTC需PS提供独立映射和有效标志。局部DOA、世界DOA、heading_referenced分别标记；IMU失效回退局部，不伪称绝对北向。声速包含温湿压的有效性/回退模式；新网络对动态声速的解码补偿仍需单独验证，不能仅凭环境数值已算出就宣称DOA精度改善。
