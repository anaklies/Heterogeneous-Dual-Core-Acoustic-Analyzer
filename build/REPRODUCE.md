# 从解压到运行及源码构建

## 1 环境与版本

Windows 10/11，Vivado/Vitis 2025.2，目标xc7z020clg484-2。ARM编译器为Vitis随附arm-linux-gnueabihf-gcc，Cortex-A9/NEON/hard-float；精确命令在 `build/recorded_commands/`。PC使用Python3.12及 `src/project/apps/sixmic-desktop/packaging/requirements-lock.txt`。软件数学数据所需依赖在 `sim/software_data_requirements.txt`。



## 2 完整性和软件参考

```powershell
python -X utf8 build/check_package.py
python -X utf8 skill/evidence-validation/scripts/self_test.py
python -X utf8 skill/evidence-validation/scripts/verify.py manifest --root . --manifest build/FILES_SHA256.json
```

预期均返回退出码0。第一项还核对45项活动目录，第二项验证可复用校验工具能正确识别匹配、错误和越界路径，第三项只检查文件哈希。

已有输入、软件实际输出与黄金参考可直接查看，无须重新运行。确需重新生成时：
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r sim/software_data_requirements.txt
.\.venv\Scripts\python.exe -X utf8 sim/generate_software_measurements.py
```
生成脚本写回软件数据目录，先复制一份工程再运行；不要覆盖留作比对的原始交付数据。原生DLL在软件测试中运行，不是FPGA执行证据。详见数据说明和SUMMARY.json。

## 3 直接恢复板卡

先按 `board/README.md` 核对接线、SD启动、串口及网络。用 `board/sd` 完整文件组恢复，不需要重新综合。`board/pc/echo/echo.exe` 是可分发的目录式程序，必须保留旁边Qt、资源及协议文件，不可只复制EXE。

## 4 PL源码重建

```powershell
powershell -ExecutionPolicy Bypass -File build/rebuild_pl.ps1 -Vivado D:/2025.2/Vivado/bin/vivado.bat
```

脚本将恢复压缩包解开到 `build/work/pl`，覆盖本包匹配的 `src/pl_project` 文件，在私有副本中生成设计，运行综合和布局布线，并输出到 `build/out/pl`。若工作目录已存在则停止，保留上次构建；自行选择新工程副本后再运行。不要使用旧的DAS/CNN研究构建脚本代替此入口。

门槛：综合/实现完成，存在建立与保持路径，所检查最差Slack非负，DRC错误为0，再输出Bitstream和XSA。当前交付报告仍存在10个输入和20个输出delay约束缺口；脚本门槛不是全部外部接口电气时序已验收的证明。

预生成IP及工程源由 `board/project/recoverable_project.zip` 提供。修改HLS核心时，先运行 `python -X utf8 build/prepare_hls_configs.py` 获得重定位配置，按Vitis2025.2运行对应组件并导出IP，再在私有Vivado工程更新IP。只重新综合旧IP不会包含HLS修改。

## 5 PS源码重建

```powershell
python -X utf8 build/rebuild_ps.py --toolchain-bin D:/2025.2/Vitis/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin --dry-run
python -X utf8 build/rebuild_ps.py --toolchain-bin D:/2025.2/Vitis/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin
```

脚本重定位已记录的编译命令，解压随包ARM sysroot，重建网关和便携界面，输出保留在 `src/project/deployment/*/build/arm` 对应目录。`board/ps/bin` 保存的是从最终FIT提取的已交付程序，不能因为重编译了候选就自动覆盖它。

内核与rootfs不是本项目重新实现；提供 `board/sd/image.ub` 作为固定可运行基线。`src/project/deployment/echo_spatial_off_20261031/` 保留最终镜像补丁与验证源码，历史脚本中仍可能引用开发机路径；在新环境使用本包重定位的镜像组装工具 `build/assemble_ps_image.py`，将显式指定的新文件替换到指定目标，保留基线镜像。

## 6 PC源码重建

```powershell
python -m venv .venv-pc
.\.venv-pc\Scripts\python.exe -m pip install -r src/project/apps/sixmic-desktop/packaging/requirements-lock.txt
powershell -ExecutionPolicy Bypass -File build/rebuild_pc.ps1 -PythonExecutable .venv-pc/Scripts/python.exe
```

输出 `build/out/pc`，保留原程序。该步骤需要锁定依赖可下载/可安装；不接板的打包自检不能代替真实声学测量。

## 7 BOOT组装与Linux边界

```powershell
powershell -ExecutionPolicy Bypass -File build/rebuild_boot.ps1 -Bootgen D:/2025.2/Vitis/bin/bootgen.bat
```

默认用 `board/boot_components` 内匹配的FSBL、Bitstream、U-Boot及DTB生成 `build/out/boot/BOOT.BIN`。如PL改变，先在工作副本内更新boot_components中的Bitstream，必要时更新XSA关联的FSBL/设备树；默认命令不会自动选择一个未知的新Bitstream。

## 8 复现结果记录

记录工具版本、源哈希、生成文件哈希、资源/时序、输入及输出。算法变化只运行受影响的最短回归；未改变源码和依赖的有效测试直接继承。真实板级输出见 `board/evidence`，软件数值对照见data，不能混用。
