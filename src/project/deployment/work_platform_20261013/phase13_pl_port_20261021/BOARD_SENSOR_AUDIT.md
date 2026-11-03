# Phase13 板卡、传感器与网口审计

日期：2026-10-21。仅依据实际工程、随附手册和软件/RTL证据；未连接实物，不宣称I2C或传感器实测通过。

## 板卡与以太网

已确认板卡为 **RK-ZYNQ7020-F V1.0，xc7z020clg484-2**。来源：

- `deployment/board_manual_review_20261012/RK-ZYNQ7020-F V1.0 开发板用户手册.txt`，原PDF来源记录于同目录`index.json`；用户手册第5、10、25页。
- `C:/Users/sunxi/Desktop/fpga_prj/02_petalinux_hdmi_config/PL/Project/petalinux_hdmi_config.xpr` 的 Part。

板载两路千兆以太网：一PS、另一PL；PHY均为RTL8211F-CG，通过RGMII连接。原厂Linux命名eth0=PS、eth1=PL。接口命名仅对原厂镜像成立，后续软件应核对MAC/设备树，不能只靠eth编号。

**建议PC通信使用PS物理网口。** 六路48kHz/24bit音频净载864000B/s，另加方向/频谱/事件仍远低于千兆链路容量。PL算法经AXI/DMA到DDR，PS仅打包传输，不执行核心声学运算。这样避免为当前需求占用PL以太网MAC、额外DMA及缓存；网络阻塞必须由有界队列隔离，不能阻塞采集。

原厂preset `C:/Users/sunxi/Desktop/fpga_prj/02_petalinux_hdmi_config/ZYNQ7020_Petalinux_Config.tcl`：GEM0启用、MIO16..27、MDIO MIO52..53、PS输入晶振33.333MHz。手册另确认PL板上50MHz晶振。不能将PS晶振频率当成PL算法时钟；算法clock需按实际设计设置。

本次核对的HDMI厂商BD没有新增PL以太网MAC实例的证据；两个物理网口并不意味着两者都在每个自建Bitstream中可用。PS网口推荐不依赖此推测。

## IMU型号与协议

用户资料为Yahboom **10轴IMU惯导模块**，采用WIT兼容寄存器/串口协议。PDF文字没有独立给出可确认的核心芯片/精确模块SKU，因此不臆造WT/JY型号。

读取原始资料：

- `D:/download/10轴IMU模块通讯协议.pdf`
- `D:/download/IMU模块简介.pdf`
- 只读Python例程 `D:/download/10轴IMU惯导模块/6.RDK X3-应用例程/imu_usb.py`

为可追溯审计，PDF文字提取保存于`tests/sensors/imu_protocol_0.txt`、`imu_protocol_1.txt`。原PDF不修改。

协议确认：

|内容|寄存器/单位|当前hub支持|
|---|---|---|
|I2C从地址|IICADDR@0x1A，默认0x50，可改0x01..0x7F|默认0x50，参数可选|
|Roll/Pitch/Yaw|0x3D..0x3F，signed16/32768×180°|10Hz读取|
|q0/q1/q2/q3|0x51..0x54，signed16/32768|10Hz读取，Q15输出|
|气压|0x45..0x46，32bit低字在前，单位Pa|1Hz读取|
|片上时间|0x30..0x33，年月/日时/分秒/毫秒|协议存在；继承hub**未读取**|
|IMU温度|0x40|继承hub未读取，声速以SHT为主|

模块资料声称串口/I2C、板上CP2102 USB串口、默认串口9600bps、I2C硬件最高400kHz、默认更新10Hz。带金属壳版本资料说明只引出USB；用户实际是否可接SCL/SDA仍需接线确认。不能把USB线接入PL I2C。

模块姿态并不等于免校准绝对北向：资料明确磁力计需环境校准并远离磁铁/扬声器等干扰。四元数有效只能证明格式、范数和新鲜度，不能证明航向未受干扰。

### 固定安装旋转

冻结声学阵列MIC1位于阵列本地+Y。若用户IMU +X朝MIC1、+Z与阵列+Z同向，则array-to-IMU固定旋转为Rz(-90°)，世界方向应采用`world_from_IMU × Rz(-90°) × array_direction`。不得修改冻结模型坐标或把MIC1悄悄改成+X。具体安装变换由主集成模块实现；本传感器子系统只提供原始Q15四元数和有效位。

## SHT30与声速

继承外部正式工程传感器核：`C:/Users/sunxi/Desktop/sixmic3D_fpga/pl/rtl/`。本次只复制到`rtl/sensors/`，不修改原文件；四个源/ROM的SHA256见`rtl/sensors/source_hashes.json`。

- SHT地址默认0x44，失败时可在0x44/0x45切换。
- 单次中重复精度0x240B，5秒一次，等待10ms后读6字节。
- 每次先break periodic 0x3093、heater off 0x3066；避免持续周期测量/加热。
- SHT温湿度均big-endian word+CRC8(poly0x31, init0xFF)，通过两个CRC且温度在-20..60°C后整包更新。湿度与温度有效性绑定，不伪造湿度。
- IMU寄存器值little-endian；温湿度CRC与IMU字节序不能混用。

`air_sound_speed.sv`为已有Cramer-1993近似，CO2假定425ppm，一套共享乘/除单元及96×32 ROM。温湿度有效域0..30°C；压力模型域75..102kPa。超出模型域回退温度近似；没有有效压力时使用标准压力，但mode明确标记。IMU原始压力可有效而不处于Cramer范围，这时不能宣称实测压力已用于模型。

环境mode：0=温度不可用，19.3°C参考；1=仅温度；2=温湿度、压力假定101325Pa；3=温湿度和有效模型域压力。模型是估计，不是声速实测/仪器标定。历史`deployment/environment_20261009/actual_sound_speed.json`有200个RTL配置样本、最大约0.00591m/s数值误差的历史证据，本轮不重复该大回归，也不把它冒充本轮实测。

## 故障、新鲜度和局部恢复

继承I2C master具备open-drain、重复起始、读ACK/NACK、clock stretch、bus-clear及50ms事务超时。缺设备不会无限等待一笔事务。继承hub保留最后一份有效数据，部分坏包不覆盖。

继承新鲜度阈值：姿态2秒、压力5秒、温湿度15秒。原hub错误位：0=IMU事务，1=SHT事务，2=SHT CRC，3=四元数范数，4=温度范围，5=压力事务/范围；6/7未使用。错误是通讯/格式提示，不是故障器件的物理鉴定。

新`environment_frame_snapshot.sv`：

- 完成环境计算后放入缓存；只在frame_start提交完整声速/对应环境采样和姿态，附frame_id。
- 温湿度与压力数据来自同一计算job；姿态为帧边界的整组Q15输入，不在帧中间改动。
- 有效性转变使旧环境缓存不再宣称被正确补偿，回退默认声速；无效姿态回退单位四元数并显式invalid。
- 环境核2048周期看门狗，仅复位该核并记录恢复次数，不因传感器丢失复位整机。
- bits8/9/10=温湿度/压力/姿态无效；bit11=环境缓存未就绪或有效性不匹配；bit12=环境核发生过超时。原sensor_faults在低8位。

时钟均为同一`clk`。若未来跨时钟域使用，需要外部CDC/FIFO，不能直接跨域接这些多位字段。

## 本轮实际验证

`tests/sensors/run_sensor_snapshot.ps1`，Vivado/xsim2025.2，真实继承声速核，仿真65400ns通过：

- 温湿度/压力mode3正常；温度降低时声速降低。
- 帧间字段不改变；frame_id、环境job、姿态整组帧锁存。
- 温湿度/压力/姿态失效时回退；恢复后重新生效。
- 独立短看门狗实例触发局部恢复，正常实例无误复位。
- 完整`sixmic_sensor_subsystem`同时elaborate，无虚构I2C从设备响应。

证据：`tests/sensors/compile.log`、`elaborate.log`、`simulate.log`，PASS标记`PASS ENVIRONMENT_SNAPSHOT valid atomic stale fallback recovery watchdog`。

未验证：本板实际I2C电气/接线、真实传感器响应、完整物理I2C从设备模型、实际航向准确度、RTC设时/掉电保持、传感器对DOA端到端收益、整板时序和资源。没有新增精确LUT/DSP数字。

## 集成接口

入口`sixmic_sensor_subsystem`参数`CLK_HZ`应设为真实算法时钟；输入frame_start/frame_id与I2C总线。输出：`snapshot_valid`、`snapshot_frame_id`、`frame_sound_speed_q16`、`frame_sound_speed_float`、`frame_environment_mode`、对应T/RH/P及valid、Q15姿态及valid、故障位、累计传感器错误和环境核恢复次数。

上层只有snapshot_valid对应数据可作为该帧配置。IMU安装旋转、方向坐标转换由上层处理；协议的片上时间尚未实现，事件时间先用单调采样计数，UTC由PS/板上RTC另行映射，不冒充IMU实时时钟已接入。
