# 轻量噪声、电平与相对隔声功能验收

日期：2026-10-21。全部新增实现仅位于本Phase14目录，历史数据只读引用。当前是软件参考，不是PL资源、真实测量或计量等级验收。

## 实现功能

`algorithms/noise_metrics.py`，版本`phase14-noise/1`：

1. A/C/Z数字频率计权，48kHz，双线性转换后的SOS实现，数字1kHz归一。支持六通道和跨块滤波状态。
2. FAST125ms/SLOW1s平方信号指数平均。输出数字均方功率与RMS；启动前5个时间常数明确标记未充分稳定。
3. 数字等效电平、最小/最大值、L10/L50/L90。Ln定义为超过该电平的时间比例，L10使用普通样本90百分位；输入必须等时间间隔。
4. 1/1倍频程PSD-bin积分及同测量链、同增益、同源设置下的分带相对电平差。元数据不一致拒绝比较；不称为Rw、DnT或标准隔声量。
5. NR参考曲线与最低包络曲线评级。内置ISO/R1996来源系数、31.5Hz至8kHz九频带，曲线取0.1dB，默认NR0至100。
6. NC参考曲线和评级已实现：使用Crystal Instruments公开的2018年传统63Hz至8kHz、NC15至70表，每5级一级，返回最低不被超出的曲线。不插值，不冒充ANSI2019扩展的16/31.5Hz、RNC或仪器认证；仍可传入来源明确的自定义表。

未经校准的原始dBFS不能输出NC/NR等级。调用方可以显式提供实际校准偏移，或输入麦克风标称灵敏度生成`nominal`偏移；后者始终`estimated=true`。标称灵敏度还必须使用与本引擎相同的数字满刻度/RMS约定，不能掩盖可能的3dB参考差异。实现没有默认擅自把INMP441的标称值当作实测。

## 实际测试

- `tests/test_noise_metrics.py`：**11项通过**，JUnit在`tests/noise_tests.xml`。
- 数学覆盖：A/C/Z频响、1kHz增益、流式分块一致、FAST/SLOW已知阶跃、正弦RMS、电平10dB比例、零信号、Ln方向、分带10dB差、NR曲线和临界频带、无声压参考拒绝评级、公开NC35曲线准确评级及35以上返回40、错误输入。
- 48kHz双线性计权在31.5Hz至8kHz的数字/模拟参考偏差：A最大约**0.544dB**，C约**0.546dB**；Z为0。16kHz处的更大翘曲单独记录在`tests/noise_environment.json`，不声称全音频带计量等级精度。
- 复用M的三房间speech/broad共**6份音频**，A/C/Z和FAST/SLOW输出有限且非负；对相同含混响录音做已知10dB缩放，分频带相对差最大误差约**1.87e-13dB**。
- 原始dBFS评级均被拒绝；显式标称偏移的NR结果标记为未校准估计。
- 这6份数据不是新独立房间；10dB比例验证证明算法数值和混合信号解释，不代表实测墙体隔声精度，也不代表目标声分离。

## 日常环境的实际意义

这些功能测量实际收到的混合声音。噪声和反射会改变测得电平/频谱，但不因此令RMS、计权或能量统计算法失效。相对隔声比较仍要求声源设置稳定、同一链路/增益、足够录音长度以及接收信号高于背景。未实现标准的多位置空间平均、接收室混响修正或背景扣除，不作建筑认证结论。

31.5Hz等低频还受实际麦克风频响和底噪限制；程序数字频带存在不等于传感器该频带已准确测量。软件生成的NR数值是指定声压换算条件下的参考评级，不能自动成为宿舍/办公室实际噪声等级。

## FPGA增量估算

仅理论运算量，不给虚构LUT/DSP：

- 六通道A计权3个SOS/通道，按每SOS5乘法约4.32M乘法/s；C计权2个SOS/通道约2.88M/s。Z无需滤波。SOS状态合计约240B（float32假设）。
- FAST与SLOW共用输入平方，各增加一阶状态。六通道双响应连同一次平方约1.44M乘法/s，状态48B。
- 等效电平、极值、分带和参考差可复用已有能量/PSD。NR曲线只是少量线性常数与比较，不需要FFT或新神经网络。
- 精确百分位在有限统计窗口保存电平样本；当前是有限批处理API。以后PL可选有界排序或带误差说明的直方图，不能把当前精确百分位换成近似后不做回归。
- 相对隔声与噪声曲线宜P2，周期电平/计权可按实际资源订阅为P1；不需要全部常开。此处没有HLS/RTL/10Hz或整板资源结果。

## 来源与版本

- [Arup Strutt NR公式及系数](https://strutt.arup.com/help/Curves/NRCurve.htm)：ISO/R1996系数；63Hz截距为35.4，500Hz采用4.8/0.974。采用公开明确系数，未从曲线图片读数。
- [Crystal Instruments公开NC表](https://www.crystalinstruments.com/blog/2018/9/27/noise-criteria-nc-curves)：2018-09-27发布，包含63Hz至8kHz的NC15–70完整12×8纵坐标，本次逐项采用，未从图片猜数。保留传统8带版本，不套用为其他扩展版本。
- [Arup Strutt NC说明](https://strutt.arup.com/help/Curves/NCCurve.htm)：确认传统NC15–70的5单位范围；本次保持5级，不增加更细插值的假精度。
- [NTi噪声曲线说明](https://www.nti-audio.com/wp-content/uploads/NTi-Audio-AppNote-Noise-Curves-2.pdf)：噪声曲线的声压频带、包络评级、测量条件与NR历史标准范围；不将NR称为现行ISO1996认证输出。
- [python-acoustics IEC61672公式参考](https://python-acoustics.github.io/python-acoustics/_modules/acoustics/standards/iec_61672_1_2013.html)：A/C传递函数与指数时间计权的公开参考定义；本实现独立编写，没有宣布仪器等级符合性。

复现：使用`phase12h_srp_dnn_salsa_20261020/.venv/Scripts/python.exe -m pytest tests/test_noise_metrics.py -q -p no:cacheprovider`。没有重复运行旧大型测试或修改旧算法。
