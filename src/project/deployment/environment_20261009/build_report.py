from pathlib import Path
import json,re,hashlib
P=Path(__file__).resolve().parent;ROOT=P.parents[1];F=ROOT.parent/'sixmic3D_fpga'
resource=P/'final_release_sequential_utilization.rpt'
assert resource.exists(),'Final whole-project resource report missing'
body=resource.read_text(errors='replace');usage={}
for name in ['Slice LUTs','Slice Registers','Block RAM Tile','DSPs']:
    m=re.search(r'\|\s*'+re.escape(name)+r'\*?\s*\|\s*([\d.]+)',body);assert m,name;usage[name]=float(m.group(1))
assert usage['Slice LUTs']<=53200 and usage['Block RAM Tile']<=140 and usage['DSPs']<=220,usage
required={'tb_compact_environment_config_rtl.log':'PASS 200','tb_sensor_i2c_hub_rtl.log':'PASS:',
          'tb_adaptive_mode_rtl.log':'PASS adaptive','tb_imu_pose_sweep_rtl.log':'PASS 64',
          'tb_covariance_6ch_rtl.log':'PASS six-channel','tb_pl_health_monitor_rtl.log':'PASS health',
          'tb_pl_noise_floor_rtl.log':'PASS noise floor','clock_rtl.log':'PASS independent',
          'bounded_cnn_rtl.log':'PASS full','track_final_cosim.log':'C/RTL co-simulation finished: PASS'}
for name,phrase in required.items():
    text=(P/name).read_text(errors='replace');assert phrase in text and 'Fatal:' not in text,name
speed=json.loads((P/'compact_grid_accuracy.json').read_text());track=json.loads((P/'tracking_gap_comparison.json').read_text());acoustic=json.loads((P/'acoustic_tracking_comparison.json').read_text())
files=[F/'pl/rtl'/n for n in ['sensor_i2c_hub.sv','air_speed_correction.sv','sensor_config_writer.sv','sixmic_pl_top.sv','sixmic_frontend_top.sv','pl_adaptive_mode.sv','pl_background_covariance.sv','pl_noise_floor.sv','imu_rotation_q16.sv','covariance_6ch.sv','cnn_v3_fixed.sv','cnn_v3_tiled.sv','clock_domain_guard.sv']]
files +=[F/'pl/hls/track_sources.cpp',F/'pl/coeff/air_delta_coeff.mem',F/'sixmic3D/sixmic3D.xpr',ROOT/'update_multisource_tracks.m']
manifest={'date':'2026-10-09','resourcesOptimizedNotRouted':usage,'activeCnnWeights':'unchanged prior production model',
    'activeTrackerIP':'pl/ip/track_sources_environment_final_20261009','newBitstream':False,
    'soundSpeedModelError':speed,'trackerDetectionInputTest':track,
    'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
(P/'release_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf8')
report=f'''# 温湿压、自动切换与跟踪验收记录（2026-10-09）

## 已实现并接入PL

SHT30每5秒单次测温湿，先退出可能遗留的周期模式（0x3093），关闭加热器（0x3066），等1ms后发送中等重复性0x240B，等10ms读取6字节并校验温度、湿度两个CRC。IMU姿态仍10Hz，气压1Hz读取0x45/0x46，低高16位合并成Pa。共用既有I²C引脚，没有增加40-pin引脚。

温度/湿度最后好数据有效期15秒；压力5秒；姿态2秒。失败不把部分数据当有效数据，压力不可用通过传感器故障详情bit5报告；PS已加中英文原因，定位继续采用标准压力。温度失效用19.3°C默认值。故障缓存不是新的测量值。

声速使用Cramer的有界近似，CO₂假定425ppm；湿压补偿域0–30°C、75–102kPa，超域或缺少湿度采用原温度公式，压力缺失采用101325Pa。并非测得绝对声速。共享定点运算/96字系数ROM在PL内运行，无PS定位计算。单次补偿约203周期，既有配置写入器复用温度换算并锁住同帧姿态、参数。

为兼容现有MUSIC核，config[0]发送“实温+声速修正/.606”的等效温度，使原核实际使用修正声速；这不是伪造传感器温度。PS读的0x030始终是SHT30真实温度，音频定位帧word4是原核使用的声速。config[14]仍为遗留值0，不能擅自改成物理温度而丢失修正。

200次真实RTL配置快照经既有MUSIC浮点公式解码验证；另对{speed['gridCases']:,}个数值网格组合扫描，最大公式近似误差{speed['maxKernelSpeedErrorMps']:.8f}m/s。该数值不代表传感器、整机声速或定位误差。SHT30自身典型温度误差约0.2°C所造成的声速不确定度更大。

## 自动切换

旧PL模式容易沿用第一次的背景状态。本轮以当前窗口/可信背景的能量代理选择普通MUSIC或CNN+背景白化，两个功能使用同一模式，避免只旁路CNN却继续使用旧白化。进入CNN的RMS代理比约0.24，退出约0.16，中间维持上一模式。PL代理使用一个采样通道的定点频域能量，与MATLAB六路RMS存在聚合和量化差别，不能宣称逐样本完全等价。

背景能量明显过时（当前能量低于旧参考的四分之一）时，废弃旧参考并一起重建谱底和背景协方差。相干发声体仍禁止作为健康背景。无需用户手切。验证了资格保护、双向切换、24个临界窗口防抖及旧强背景废弃。规则正确不等于有真值支持的“每帧全局最优”；等能量但谱/方向改变仍属于进一步背景适应课题。

## 跟踪改进

已确认轨迹短缺失保留6帧，未确认候选保持原3帧；无观测期间只作带held标志的预测并衰减速度。PL既有dt≈0.2133s，因此确认轨迹最多保留约1.28s，然后过期；不存在无限驻留。恢复有效观测时重接测量，避免首候选13cm的预测滞后，5cm静止死区保留。

9组给定检测位置的1/2/3目标实验，包含两次五帧无声段：ID变化{track['before']['IDchanges']}→{track['candidate']['IDchanges']}，新鲜坐标均值均为{track['candidate']['meanFreshErrorCm']:.4f}cm、最大均为{track['candidate']['maxFreshErrorCm']:.4f}cm，无声段冒充新测量的坐标为0。此处是关联器误差，不是声学定位误差。

240帧独立MATLAB黄金C/RTL比对通过，最大Q16偏差1。默认MATLAB入口额外通过静止、三目标、真实安静双目标交叉、960帧黄金和环境状态回归。

生产C/HLS声学模型的四组轨迹各40帧、统一输入进行比较（协方差模拟、单位CNN权重，非完整PCM或实物）：移动双源ID变化2→0，均值3.183→3.149cm；交叉双源ID变化12→7，均值5.901→5.295cm，OSPA数量惩罚22.497→18.444cm；静止及移动三源误差不变。**交叉歧义没有全部消除。** 相同位置、相干窄带或较长静音后仅凭声音不能保证唯一实体身份；本轮没有声音类别或声纹分类。

## 精度/CNN候选筛选

原合格CNN保留，未为完成任务换上负优化模型。尝试了三窗口距离一致性恢复、宽频支持子集以及空间/角度排斥约束：距离恢复未提高有效坐标，频率子集虽增加输出却减少10cm内目标且增大误差，空间/角度改法增加漏检或假源，均未进入默认版本。没有证据声称本轮有效坐标匹配已进一步提高，不能将平均值漂亮当作进步。

原90场景MATLAB独立基线仍为：条件匹配坐标均值2.85cm、P95 12.31cm；名义2m（实际±10%）组均值6.00cm、P95 18.97cm，仅26/60目标得到有效匹配坐标。不是所有目标2m内10cm。PLC实际默认CNN仍是旧生产系数；本轮没有补齐WPE/重叠CNN/全部时间支持的等价移植。

## 资源与边界

完整主工程synth_design+opt_design资源：{json.dumps(usage,ensure_ascii=False)}。没有削减音频采样/权重数值精度，采用计时器与算子共享、规范化姿态的无损紧凑存储、计数器实际范围限定和空闲DSP映射。CNN1740个掩码逐位比对通过；64姿态576个系数逐位一致；协方差21项、背景1785项、CRC/过期恢复、时钟丢失有限恢复、看门狗及10个PS原生IPC场景通过。

综合阶段DRC列出901项：737条Warning、164条Advisory，当前报告没有Error或Critical Warning。主要涉及DSP流水线，以及RAM异步控制检查；RAM规则达到报告数量上限，因此901不是全部潜在告警数量。上述警告仍需结合布局布线时序及复位实现评估，不能解释为全部无害。

这是综合优化资源，不是最新布局布线、完整六路PCM→三坐标/ID的RTL精度或板卡声学验收。没有生成新比特流，旧bitstream不包含本轮修改。BRAM达到满载，后续新增显示链或算法仍需整体资源与实时性优化。不能宣称“所有bug、所有身份歧义均已解决”。

## 证据

本目录RTL日志、actual_sound_speed.json、compact_grid_accuracy.json、tracking_gap_comparison.json、acoustic_tracking_comparison.json、拒绝候选JSON和release_manifest.json记录输入口径、结果与源码SHA256。

资料：[SHT3x官方手册](https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf)、[Cramer公开实现](https://pyfar.readthedocs.io/en/v0.8.0/_modules/pyfar/constants/speed_of_sound.html)。
'''
(ROOT/'results/ENVIRONMENT_TRACKING_ACCEPTANCE_20261009.md').write_text(report,encoding='utf8')
print(json.dumps(usage,ensure_ascii=False));print(ROOT/'results/ENVIRONMENT_TRACKING_ACCEPTANCE_20261009.md')
