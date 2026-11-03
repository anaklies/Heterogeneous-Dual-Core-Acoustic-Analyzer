# 当前PL功能与有界分层资源审计（2026-10-24）

范围：只读核查已冻结RC1、实际整板分层报告、服务生成入口及已有验证结果。未修改算法/RTL/Bitstream，未运行综合、布线或逐帧长测试。历史190/620冻结保持不变。

## 功能统计与运行条件

52条历史功能记录中，自动SRP-DNN 1条已删除；其余51条：9条内建硬件记录、42条共享微程序记录（逐窗PSD已有P0通路，Welch历史处理另由后台执行）。检查了全部42条记录引用的程序文件，未发现缺失源码；已有32个代表调用案例及后续受影响小回归。**这不是51项完整服务均已实板验收，也不是烧入bit后全部自动启动。**

当前bit包含实际I2S、CDC、窗口DMA、FFT/IFFT、标量执行器、调度、事件留证、传感器和主机接口。42项程序必须由PS加载描述符/程序/系数后在PL执行；Python只组织配置，不在PS替代声学计算。默认镜像只包含11个P1服务族；其余按需选择。正确的Linux保留DDR、上传和配置激活仍是实机前提。

默认P1服务族：snapshot、peak_hold、spectrum_ema、smoothing、octave、third_octave、shape、flux_delta、welch、frequency_drift、selected_pair_CSD。**原清单的P0/P1/P2分级是用途分级，不等于每项当前都在默认轮询。**精确FAST/SLOW是连续录音专用任务，手动DAS等需选择相应服务；详细入口以services/deployment_profiles.py与sdk说明为准。

事件闭环、FFT及标量核、槽头、游标、传感器失联已有分层/联合RTL证据；没有发现本次需要新长仿真的代码变更。所有实板运行结论保持NOT TESTED。没有承诺“无Bug”。

## 完整清单

|ID|功能|实际实现落点|注意|
|---|---|---|---|
|io_pcm|六通道WAV/PCM|PL内建链路|已有分层RTL；实板未测|
|levels_core|RMS/Peak/dBFS/波峰因数/削顶|PL内建链路|已有分层RTL；实板未测|
|data_continuity|采样连续性与异常输入|PL内建链路|已有分层RTL；实板未测|
|fft|FFT幅度谱|PL内建链路|已有分层RTL；实板未测|
|psd|Welch PSD|PL共享程序：analysis_statistics.py|已验证数值/代表调用；完整服务实板未测|
|stft|STFT与瀑布数据|PL内建链路|已有分层RTL；实板未测|
|spectrum_average|谱功率平均|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|spatial_interface|分析结果与手动空间图接口|PL内建链路|已有分层RTL；实板未测|
|srpdnn_main|单主方向SRP-DNN|已删除|不是当前功能|
|signal_quality|输入有效性与新鲜度（无自动方向）|PL内建链路|已有分层RTL；实板未测|
|levels_extended|Peak-to-Peak及扩展电平|PL内建链路|已有分层RTL；实板未测|
|octave|1/1倍频程|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|third_octave|1/3倍频程|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|peak_hold|谱峰值保持|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|smoothing|谱平滑|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|frequency_tracking|主峰频率跟随|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|frequency_drift|频率漂移|PL共享程序：frequency_drift.py|已验证数值/代表调用；完整服务实板未测|
|directed_das|指定方向频谱|PL共享程序：manual_das.py|用户指定方向，无自动DOA，不是完整声源分离|
|csd|CSD/CSM|PL共享程序：cross_spectral_services.py|已验证数值/代表调用；完整服务实板未测|
|coherence_phase|相干性与相位差|PL共享程序：cross_spectral_services.py|已验证数值/代表调用；完整服务实板未测|
|energy_change|短时能量变化|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|band_tracking|频带能量跟踪|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|centroid|谱质心|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|flatness|谱平坦度|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|event_trigger|声音变化事件服务|PL内建链路|已有分层RTL；实板未测|
|frequency_time_weighting|A/C/Z与FAST/SLOW|PL共享程序：noise_services.py + recorded_time_response.py|A/C/Z相对量；FAST/SLOW需连续记录，非默认实时精确计权|
|level_statistics|LeqFS及L10/L50/L90|PL共享程序：noise_services.py|已验证数值/代表调用；完整服务实板未测|
|zoom_fft|Zoom FFT|PL共享程序：extra_spectral.py|已验证数值/代表调用；完整服务实板未测|
|fundamental|基频/周期估计|PL共享程序：linear_periodic.py|已验证数值/代表调用；完整服务实板未测|
|harmonic_ratio|谐波与有限带宽THD|PL共享程序：extra_spectral.py|已验证数值/代表调用；完整服务实板未测|
|sidebands|指定载频边带|PL共享程序：extra_spectral.py|已验证数值/代表调用；完整服务实板未测|
|envelope_hilbert|Hilbert包络|PL共享程序：p2_chains.py|已验证数值/代表调用；完整服务实板未测|
|envelope_spectrum|包络谱|PL共享程序：p2_chains.py|已验证数值/代表调用；完整服务实板未测|
|modulation_spectrum|调制谱|PL共享程序：p2_chains.py|已验证数值/代表调用；完整服务实板未测|
|autocorrelation|自相关|PL共享程序：linear_periodic.py|已验证数值/代表调用；完整服务实板未测|
|full_das|全空间DAS功率图|PL共享程序：das_map.py|已验证数值/代表调用；完整服务实板未测|
|band_das|带限DAS空间图|PL共享程序：das_map.py|已验证数值/代表调用；完整服务实板未测|
|cross_correlation|互相关|PL共享程序：linear_periodic.py|已验证数值/代表调用；完整服务实板未测|
|gcc_phat|GCC-PHAT时延观察|PL共享程序：linear_periodic.py|已验证数值/代表调用；完整服务实板未测|
|spectral_flux|谱结构变化|PL共享程序：programs.py|已验证数值/代表调用；完整服务实板未测|
|spectrum_freeze|频谱冻结和A/B|PL共享程序：analysis_statistics.py|已验证数值/代表调用；完整服务实板未测|
|relative_limit|相对限值检测|PL共享程序：analysis_statistics.py|已验证数值/代表调用；完整服务实板未测|
|cepstrum|实倒谱|PL共享程序：p2_chains.py|已验证数值/代表调用；完整服务实板未测|
|spectral_kurtosis|谱峭度有限原型|PL共享程序：extra_spectral.py|已验证数值/代表调用；完整服务实板未测|
|spatial_grid|球面网格|PL共享程序：das_map.py|已验证数值/代表调用；完整服务实板未测|
|spatial_peaks|空间图局部峰辅助|PL共享程序：das_map.py|已验证数值/代表调用；完整服务实板未测|
|room_decay|EDT/T20/T30|PL共享程序：room_services.py|需有效IR/明确起点的衰减输入，不可对任意持续声直接测房间|
|relative_insulation|相对隔声|PL共享程序：noise_services.py|无校准/参考条件仅相对或实验结果，非认证指标|
|stipa_experimental|实验STIPA|PL共享程序：stipa_graph.py + stipa_offline.py|101阶段完整Native数值通过；PL完整耗时未测、慢速实验|
|noise_rating|NC/NR估计|PL共享程序：noise_services.py|无校准/参考条件仅相对或实验结果，非认证指标|
|room_clarity|C50/C80/D50|PL共享程序：room_services.py|需有效IR/明确起点的衰减输入，不可对任意持续声直接测房间|
|spectral_decay|分频衰减数据|PL共享程序：room_band_decay.py|需有效IR/明确起点的衰减输入，不可对任意持续声直接测房间|

清单外系统配套：SHT30/气压/IMU与声速、麦克风健康、事件双bank租约、自检故障位、原音CUR1、FFT防混帧槽头、C/ARM调用库均有实现。LCD循环彩蛋有资产与ARM播放器，播放本身由PS软件负责；整机看门狗也依赖实际Linux驱动/服务，不能归成已实机验证的PL自治功能。

## 同一个已布线设计的资源

下面六行互不重复，LUT总和40137；不是把OOC数字相加。

|区域|LUT|占全板LUT用量|
|---|---:|---:|
|共享标量执行核|9941|24.77%|
|FFT/IFFT及其数值/访存包装|8419|20.98%|
|采集、窗口、调度、事件处理pipeline|11566|28.82%|
|其他仪器控制、传感器、留证与包装|4017|10.01%|
|仪器DDR共享互连|2110|5.26%|
|其余板级显示、控制及互连|4084|10.17%|

全板：40137 LUT / 42117 FF / 13114 Slice / 88 DSP / 57.5 BRAM36等价；WNS +0.149ns、WHS +0.036ns，TNS/THS0。片上受约束路径通过，不代表8输入/8输出电气延时签核通过。

现有分层表没有逐模块独占Slice；同一个Slice可能容纳不同层次逻辑，不能用LUT百分比直接伪造模块Slice占用。当前13114个占用Slice平均3.061个LUT（每Slice最多4个）、3.212个FF（最多8个），LUT装箱约76.5%、FF约40.1%。这是容量和装箱同时受限，不是所有空FF都能随意拿来替代LUT。

**70% Slice的硬下界：**70%只有9310个Slice，最多37240个LUT位置；当前40137个LUT即使完全理想装箱也至少10035个Slice（约75.45%）。因此只调布局/控制集合不可能把当前逻辑压到70%；至少还需减少2897个LUT，且这只是理想必要条件，不是可达保证。

## 有界优化判断（不改冻结版）

1. **首选：事件特征/检测的时间复用。**features3664 LUT、detector2538 LUT，合计6202。源码有8路并行64位频带累加/动态门控、8路阈值及自适应更新。与输入刷新间隔相比可研究用一个较窄累加/比较通路轮询8频带，但必须保留饱和、故障和背景锁定语义，并确认DDR等待和窗口预算。模块足够大，有实质优化机会；还没有候选综合数据，不能声称能省去6202或指定比例。
2. **其次：共享标量核的状态和访存开销。**9941 LUT/8230 FF；自身控制约1475 LUT/4648 FF，读辅助1248 LUT，写辅助618 LUT，AXI主接口786 LUT。检查点搬运、描述符检查、16字行缓存值得针对性研究。浮点寄存器f/u已经用BRAM，不能再把“改成BRAM”当成没做过的新收益；也不能删输入保护/原子发布来节约面积。进一步重构属于中等工作量，收益须量测。
3. **第三：HOST配置/结果寄存器。**1814 LUT/3786 FF。可研究较慢寄存器文件/BRAM及串行快照发布，但必须保留32字原子配置、版本和复制安全；不能单纯减掉必要缓冲。可能改善控制集合和FF装箱，实际Slice收益未知。
4. **互连不再是第一大户。**新的仪器DDR互连只有2110 LUT；前次面积向共享互连已实际降低总资源。继续改AXI收益上限有限且有吞吐/兼容风险，不建议首先再动它。
5. FFT本体变换层约1876 LUT；整个FFT包装8419 LUT还包含缩放、sqrt/log/div、访存和控制。不能把8419都算作FFT蝶形浪费。改定点、跨核共享复杂算子将触发精度/调度回归，不是快速无风险压缩。
6. 不建议为了面积删掉传感器、自检、事件保护；也不建议现在大改厂商HDMI/PS配套。DSP和BRAM约40%并非必须压低；如适度增加它们能明显减Slice，反而符合合理资源使用。

已拒绝CE控制集合改写：LUT43029→43275，Slice13256→13264，没有面积收益。本次不再重复该试验。没有开展参数穷举、新综合或布线。

## 明确结论

当前是**已能容纳、数学核已共享，但Slice余量不理想，部分低速控制/事件路径还有结构性优化空间**。不属于“项目功能必然太大装不下”，也不能评价为“所有片上资源已经理想利用”。存在值得做一次候选实验的较大模块，尚无证据保证Slice70%。优先只试事件通路时间复用；净收益明显再保留，否则停止。保持本次RC1 bit/XSA及哈希不变，便于用户先做实物验证。
