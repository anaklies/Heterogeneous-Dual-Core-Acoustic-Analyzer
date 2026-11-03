# 板载 LCD 循环彩蛋：隔离候选

本目录只提供可选 PS Linux 小进程与离线转换素材，不修改旧目录、生产启动项、PL 工程或定位链路。没有运行 Vivado，也没有连接实物屏幕。本次无网络委派；已考虑本地 DeepSeek 技能，但任务要求不向网络发送内容。

## 硬件证据

原始资料：`C:/Users/sunxi/Desktop/2_硬件资料/1_hardware/ZYNQ7020-F V1.0原理图.pdf`。第 12 页 LCD1 标注 **1.47 英寸 IPS 172×320**，SCL/SDA/DC/CS/RESET 和背光；第 5 页 PDF 网络文字明确给出下表。与仓库 `deployment/system_candidate_20261012/system_pins.xdc` 一致。

| LCD 网络 | FPGA 球位 | 现有 PS/EMIO 接法 |
|---|---|---|
| LCD_SCL | V18 | SPI0 SCK |
| LCD_SDA | U19 | SPI0 MOSI |
| LCD_CS | AA13 | SPI0 SS0，低有效 |
| LCD_DC | W13 | GPIO EMIO0，Zynq gpiochip line 54 |
| LCD_RST | AA18 | GPIO EMIO1，line 55 |
| LCD_LED | Y13 | GPIO EMIO2，line 56，背光高有效 |

控制器确切料号**未从已读资料证实**；厂家 1.47 IPS 源码使用 ST7789 类命令集，不能凭命令集宣称已确认芯片。厂家资料 `C:/Users/sunxi/Desktop/2_硬件资料/2_芯片手册/LCD/02-1.47IPS程序源码.zip` 的 `lcd_init.c`/`lcd_init.h` 可证：横屏 320×172，RGB565 高字节先发，横屏行地址偏移 34，MADCTL 方向 3 为 `0xA0`。本目录保存厂家初始化文本快照 `vendor_lcd_init.c.txt`，实际驱动继承已有 `deployment/sixmic_lcd_gif_20261012.cpp` 的初始化与 PS SPI 传输，未新造芯片初始化。

现有驱动需要加载的 PL bitstream 已把 PS SPI0 和 3 根 EMIO 引到这些引脚、Linux 启用 Zynq gpiochip，且 SPI0 无其他占用。本次没有验证当前上板镜像具备这些条件。

## 素材与播放

用户 GIF `C:/Users/sunxi/Desktop/69f52e3f64c2e7sT.gif`，599×497、42 帧，每帧 100 ms，名义循环 4.2 秒。Pillow 顺序解码合成透明/局部更新帧，再按比例缩放、黑底居中，生成 320×172 RGB565。首帧预览 `easter-egg.png`。原文件、逐帧与整包 SHA256 均在 `easter-egg.json`。

`easter-egg.lcd` 为 4,623,544 字节；头部 `<8sHHI`（小端）=`S6LCD01\0`、320、172、42；每帧为 `<I` 毫秒延迟 + 110080 字节行优先 RGB565（像素大端）。常驻像素约 4.62 MB。播放器读取完整且校验后的包，循环逐帧写屏；每帧等待量扣除传输耗时，过慢时按实际速度继续。10 fps 是素材节奏，未测实物吞吐。

使用 bundled Python 重新生成（需 Pillow）：

```powershell
& C:/Users/sunxi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe ./convert_gif.py C:/Users/sunxi/Desktop/69f52e3f64c2e7sT.gif ./easter-egg.lcd
& C:/Users/sunxi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe ./prepare_player.py
& C:/Users/sunxi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe ./verify_lcd.py
```

所有命令在本目录执行。`prepare_player.py` 从只读旧驱动重建候选；`verify_lcd.py` 使用已有 ARM 工具链/sysroot 独立编译 `sixmic-lcd-player`，并在 QEMU 运行 ARM 包解析测试。编译命令、编译日志、运行日志与汇总分别为 `build_command.json`、`arm_build.log`、`qemu_lcd.log`、`verification.json`。

准备好目标板已有 Linux/QtCore 运行库后，手动把二进制与素材放到自选目录，在板端执行：

```sh
. /etc/sixmic/runtime.env
mkdir -p /run/sixmic
./sixmic-lcd-player --test --asset ./easter-egg.lcd
./sixmic-lcd-player --asset ./easter-egg.lcd
```

默认使用 `/dev/spidev0.0`，SPI mode 3、8 bit、请求 16.666666 MHz；每次传输不超过 4096 字节。`--reserved-spi0` 才允许继承驱动的 `/dev/mem` 备用路径，而且设备树 `/amba/spi@e0006000/status` 必须恰为 `disabled`；该路径继承 FSBL 的时钟配置，固定分频 /16（原驱动注释所述 166.67 MHz 参考时钟下约 10.42 MHz）。不要在内核或其他进程管理 SPI0 时使用它。当前板是否满足条件未验证。

进程以独占锁避免多个彩蛋播放器互抢屏，遇到 GPIO/设备/传输错误退出，支持 Ctrl+C/SIGTERM 关闭背光；不重启主 UI、定位程序或整板。没有自动注册启动服务，也没有修改已有程序。

## 验证边界

实际结果以 `verification.json` 与 `qemu_lcd.log` 为准。转换检查涵盖尺寸、帧数、42 个帧延迟、RGB565 红绿蓝字节序、逐帧哈希与确实存在动画变化；ARM QEMU 将整包像素摘要与主机摘要对照，并拒绝截断、错尺寸、零延迟和缺失文件。`--test` 完全不打开 GPIO/SPI。

QEMU 通过只证明 ARM 编译、解析和数据一致，**不证明屏幕点亮、SPI 时序、色序、方向、持续帧率或当前 PL 路由正确**。实物验收尚需：先显示首帧核对方向/色彩，再观察完整循环及退出背光行为。确切控制器料号和现用板卡版本也待现场核对。
