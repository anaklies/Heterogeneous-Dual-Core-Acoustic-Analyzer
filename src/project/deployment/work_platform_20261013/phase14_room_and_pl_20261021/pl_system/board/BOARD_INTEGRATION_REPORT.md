# 新隔离板级BD集成结果

状态：`validate_bd_design` 与wrapper生成通过；仅板级基础设施验证，不是算法整机验收。Vivado2025.2、xc7z020clg484-2。没有运行综合、布局布线、bitgen或烧录。

## 已实现

- 从 `deployment/system_candidate_20261012/vendor_bd/design_1.bd` 私有复制BD及其IP，不编辑旧工程。
- 原PS7 DDR/MIO、HDMI/VDMA、LCD和HP0显示路径保留。
- 新 `S_AXI_ACOUSTIC` 接受真实声学PL主机的32-bit AXI4事务；显式异步AXI Clock Converter跨75→100MHz，三级同步；SmartConnect单时钟100MHz完成32→64bit及AXI4→AXI3适配，再接PS7 HP1。
- 新MMCM由既有100MHz FCLK0生成75MHz计算时钟；原音频采集时钟没有改变。参数为100×40.125/(4×13.375)=75MHz。该算式及BD验证不等同于实现后时钟/时序验收。
- 复位由MMCM locked及PS FCLK_RESET0_N经proc_sys_reset产生，验证输入复位极性为低有效。
- GP0旧邮箱接口与地址不变。新增中断输入接IRQ_F2P[2]；软件GIC/设备树绑定尚未验收。

## 地址与端口

|用途|接口|地址/时钟|
|---|---|---|
|PS配置/状态|`M_AXI_MAILBOX_*`，32-bit AXI-Lite|0x43C20000，64KiB，`mailbox_clk`100MHz、`mailbox_resetn`|
|PL访问DDR|`S_AXI_ACOUSTIC_*`，32-bit AXI4，ID1，最大16beats|映射HP1 DDR_LOWOCM 0x00000000–0x3fffffff；入口75MHz|
|计算时钟/复位|`acoustic_clk_75`、`acoustic_resetn_75[0:0]`|输出75MHz、同步释放低有效复位|
|中断|`acoustic_irq`|输入，接PS IRQ_F2P[2]|

DDR映射只表示地址可达，**未为Linux预留任何内存**。集成后必须仅访问合法DMA/保留内存，处理缓存一致性及显示HP0竞争。

完整展开端口见已生成 `design_1_wrapper.v`。`S_AXI_ACOUSTIC_` 后缀为：

- 输入：araddr[31:0]、arburst[1:0]、arcache[3:0]、arid[0:0]、arlen[7:0]、arlock[0:0]、arprot[2:0]、arqos[3:0]、arregion[3:0]、arsize[2:0]、arvalid；awaddr[31:0]、awburst[1:0]、awcache[3:0]、awid[0:0]、awlen[7:0]、awlock[0:0]、awprot[2:0]、awqos[3:0]、awregion[3:0]、awsize[2:0]、awvalid；wdata[31:0]、wlast、wstrb[3:0]、wvalid、bready、rready。
- 输出：arready、awready、wready、bid[0:0]、bresp[1:0]、bvalid、rdata[31:0]、rid[0:0]、rlast、rresp[1:0]、rvalid。
- 本次最终wrapper没有USER或WID端口。

## 证据与复现

`build_location.txt`记录私有工程路径；其中`project/acoustic_board.xpr`、`assets/vendor_bd/design_1.bd`及`assets/generated/design_1/hdl/design_1_wrapper.v`为当前产物。

创建入口：`vivado -mode batch -source create_board_bd.tcl`，仅克隆/验证/生成wrapper。`refine_existing_clone.tcl`是本次一次性增量CDC修正记录，不要对最终工程重复执行。

日志：`validate_board_access.log`首次克隆验证通过；`validate_explicit_cdc.log`最终显式CDC验证退出0。`validated_properties.txt`保存配置读回。其`CORE_CLKOUT_ACTUAL`标签实际读取的是请求频率，不是实测频率。

最终生成BD的clock-domain名字仍继承FCLK0元数据，但路径使用明确`ACLK_ASYNC=1`异步转换器，不依赖名字推断CDC。尝试写只读CLK_DOMAIN属性产生的无效警告已从重建脚本删除；没有据此添加false-path。

## 尚未连接与发布门槛

1. 声学实际AXI主机/仲裁器、NN/FFT/DSP计算核仍需接入S_AXI_ACOUSTIC；不能用常量结果冒充算法。
2. `analysis_axi_control`需在物理顶层接M_AXI_MAILBOX；若运行75MHz，复用已有100→75MHz guarded AXI-Lite bridge。能力/算法版本必须根据真实已实现计算核报告，缺核时为0，不宣称全集完成。
3. IRQ跨域处理、frame/config epoch、故障、看门狗恢复、AXI超时及DMA异常仍需整机验证。
4. 物理I2S/IMU/SHT30顶层、传感器与算法时钟边界、真实引脚及外部时序约束尚未纳入此BD；`integration_constraints.xdc`只是说明，没有豁免路径。
5. Linux保留内存、驱动、设备树/中断、FSBL/XSA匹配尚未生成/验收。
6. 全工程资源、CDC/DRC、实现后setup/hold、持续吞吐及板上测试均NOT TESTED。本次没有新bitstream/XSA/BOOT。

工具警告还包括继承的SPI SSIN建议、旧工具IP迁移建议、AXI基础设施自动配置提示；不能由BD验证推断这些已完成整机审查。
