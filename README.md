# ECHO 双核共享六通道声学分析仪

本工程面向设备声音检查、频谱比较、房间声学实验和异常声音记录。在RK-ZYNQ7020-F的XC7Z020-2CLG484上，使用一套2048点FFT/IFFT模块和一套可编程标量核共享执行45项功能，PS负责设备管理、触摸界面、文件与网络，Windows客户端负责控制、显示及导出。


## 从哪里开始

| 目的 | 入口 |
|---|---|
| 看懂作品与设计取舍 | [设计报告](report/ECHO_设计报告.md)，同目录提供DOCX |
| 按顺序复现 | [完整复现说明](build/REPRODUCE.md) |
| 核对45项功能 | [功能与证据清单](report/45项功能与证据.csv) |
| 检查文件未损坏 | `python -X utf8 build/check_package.py` |
| 不接板查看输入与参考 | [软件数据说明](data/software_measurements/数据说明.md) |
| 查看目标板优化前后对比 | `build/vivado_evidence/performance/` 与 `sim/inherited_results/performance_resource_comprehensive_20261025/` |
| 恢复上板运行 | [板卡运行与回退](board/README.md) |
| 复用研发方法 | [技能包](skill/README.md) |
| 查看设计协作与纠错 | [协作记录](report/大模型协作记录.md) |
| 按赛事条款检查 | [提交要求对照](report/提交要求对照.md) |

## 目录

`src/`：RTL/HLS/PS/PC源码，`src/project` 保留原相对依赖，`src/pl_project` 对应物理实现工程；`sim/`：验证脚本与历史结果；`build/`：构建入口、实现报告、哈希；`board/`：SD启动包、Bitstream/XSA、恢复工程与实测记录；`data/`：输入及参考结果；`skill/`：通用技能包；`report/`：设计报告、配图、设计决策及大模型交互摘录。

## 关键实测指标

6路24-bit同步采样，实际采样率约48009.775Hz；分析时钟50MHz。最终整板LUT40127、FF42117、DSP88、BRAM36等效57.5；已约束路径WNS +0.149ns、WHS +0.036ns。历史目标板P0发布约11.721Hz。7组代表任务28次配对调用，执行阶段时延降低15.76%～74.68%，输出逐字一致且硬件资源增量为0。具体输入、版本、统计口径和约束缺口见设计报告，不能把短测试外推为所有功能长期并发保证。

## 最短复现

1. 保持解压后的目录结构，安装Python 3.12，先运行 `python -X utf8 build/check_package.py`。
2. 不接板查看 `data/software_measurements/45项输入结果参考索引.csv`：45项有输入/参考入口，其中92项原生内核软件用例由6组快速测试导出；参考夹具不等于45项板级验收。
3. 板卡使用配套SD根目录文件，按 `board/README.md` 接线和启动；启动文件使用 `board/sd` 的完整匹配组合。
4. 启动 `board/pc/echo/echo.exe`，PS网口直连PC，设备地址192.168.77.2，TCP48120/48121。电脑同一网卡配置192.168.77.1/24，避免与已有网段冲突。
5. 修改源码后按 `build/REPRODUCE.md` 分别重建PL/PS/PC，再组装镜像。不要把不匹配的新旧文件混合写卡。

## 构建范围与来源

Vivado/Vitis使用2025.2；器件、编译器参数及Python锁定依赖已记录。恢复项目和预生成IP包含在包内。提供可运行二进制Linux/FIT基线；本项目源码重建和现成镜像运行的具体边界见复现说明。
