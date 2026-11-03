# 功能目录（真实状态，52 行逐行继承 FUNCTION_EXECUTION_MAP.csv）

生成时间：2026-10-24；来源 CSV sha256：8d77663ec4d645cdb65cf00c73c77058f585a27ac247d9c92788dd4c04ca8823
状态统计：available=0，experimental=42，not_ready=9，unsupported=1（共 52 行）

> available 必须同时具备真实后端/固件支持与验收证据。当前没有任何一行满足，
> 因此 available=0 是**如实状态**，不是缺失；不得为了打开界面而改成 available。

| featureId | 名称 | 组 | Tier | 状态 | 单位 | 输入 | 更新方式 |
|---|---|---|---|---|---|---|---|
| io_pcm | 六通道WAV/PCM | input_levels | P0 | not_ready | digital full scale (24-bit PCM codes) | six I2S channels, raw ring | continuous |
| levels_core | RMS/Peak/dBFS/波峰因数/削顶 | input_levels | P0 | not_ready | dBFS / ratio | six channels FFT+time domain | per FFT window (~11.72 Hz candidate) |
| data_continuity | 采样连续性与异常输入 | input_levels | P0 | not_ready | count / flag | raw frames + window timeline | per window |
| fft | FFT幅度谱 | spectrum | P0 | not_ready | FS amplitude per bin | 2048-sample window, 1025 bins | per window |
| psd | Welch PSD | spectrum | P0 | experimental | FS^2/Hz (Welch cumulative) | selected channel, 2048 Hann, non-overlapping retained frames | per P1 carousel |
| stft | STFT与瀑布数据 | spectrum | P0 | not_ready | FS^2/Hz | 2048-sample window, hop 512 | per window |
| spectrum_average | 谱功率平均 | spectrum | P0 | experimental | FS^2/bin | shared FFT + scalar history | per P1 carousel |
| spatial_interface | 二维/三维共用数据 | spatial | P0 | not_ready | m / unit vector (interface only) | shared FFT + scalar programs | per service publication |
| srpdnn_main | 单主方向SRP-DNN | removed | P0 | unsupported | n/a | removed | removed |
| signal_quality | 输入与方向有效性/新鲜度 | input_levels | P0 | not_ready | validity flags | window timeline + fault words | per window |
| levels_extended | Peak-to-Peak及扩展电平 | input_levels | P1 | not_ready | dBFS / ratio | six channels | per window |
| octave | 1/1倍频程 | octave | P1 | experimental | FS^2 relative band energy | 2048 FFT bins 1..966 | per P1 carousel |
| third_octave | 1/3倍频程 | octave | P1 | experimental | FS^2 relative band energy | 2048 FFT bins 2..767 | per P1 carousel |
| peak_hold | 谱峰值保持 | spectrum | P1 | experimental | FS^2/bin | shared FFT + history | per P1 carousel |
| smoothing | 谱平滑 | spectrum | P1 | experimental | FS^2/bin | triangular smoothing over 1025 bins | per P1 carousel |
| frequency_tracking | 主峰频率跟随 | frequency | P1 | experimental | Hz | dominant FFT peak | per P1 carousel |
| frequency_drift | 频率漂移 | frequency | P1 | experimental | Hz, Hz/s | dominant FFT peak + history | per P1 carousel |
| directed_das | 指定方向频谱 | spatial | P1 | experimental | FS^2/Hz (user-specified direction) | shared FFT + user direction | per P2 task |
| csd | CSD/CSM | correlation | P1 | experimental | FS^2/Hz, rad, dimensionless | selected channel pair, 1025 bins, count>=2 | per P2 task |
| coherence_phase | 相干性与相位差 | correlation | P1 | experimental | dimensionless, rad | same as CSD | per P2 task |
| energy_change | 短时能量变化 | events | P1 | experimental | FS^2 ratio | temporal features | per P1 carousel |
| band_tracking | 频带能量跟踪 | events | P1 | experimental | FS^2 per band | temporal features + band edges | per P1 carousel |
| centroid | 谱质心 | frequency | P1 | experimental | Hz | spectral shape | per P1 carousel |
| flatness | 谱平坦度 | frequency | P1 | experimental | dimensionless | spectral shape | per P1 carousel |
| event_trigger | 声音变化事件服务 | events | P1 | not_ready | event record + flags | feature/detector/recorder + clip mailbox | on event |
| frequency_time_weighting | A/C/Z与FAST/SLOW | weighting_stats | P1 | experimental | A/C/Z weighting, FAST/SLOW | every raw frame required | per raw frame (not guaranteed by ordinary P1 carousel) |
| level_statistics | LeqFS及L10/L50/L90 | weighting_stats | P1 | experimental | LeqFS, L10/L50/L90 | level history | per P1 carousel |
| zoom_fft | Zoom FFT | spectrum | P2 | experimental | FS^2/bin | P2 spectrum zoom | per P2 task |
| fundamental | 基频/周期估计 | periodic | P2 | experimental | Hz | 1024-sample linear correlation, default 100-2000 Hz | per P2 task |
| harmonic_ratio | 谐波与有限带宽THD | periodic | P2 | experimental | ratio / % | fundamental + harmonics | per P2 task |
| sidebands | 指定载频边带 | periodic | P2 | experimental | ratio | specified carrier + sidebands | per P2 task |
| envelope_hilbert | Hilbert包络 | periodic | P2 | experimental | FS envelope | Hilbert transform chain | per P2 task |
| envelope_spectrum | 包络谱 | periodic | P2 | experimental | FS^2/bin | envelope spectrum chain | per P2 task |
| modulation_spectrum | 调制谱 | periodic | P2 | experimental | FS^2/bin | modulation chain | per P2 task |
| autocorrelation | 自相关 | correlation | P2 | experimental | normalized correlation | linear correlation, 1024 samples | per P2 task |
| full_das | 全空间DAS功率图 | spatial | P2 | experimental | FS^2 (user-scan map) | shared FFT + scan grid | per P2 task |
| band_das | 带限DAS空间图 | spatial | P2 | experimental | FS^2 (band-limited map) | shared FFT + band grid | per P2 task |
| cross_correlation | 互相关 | correlation | P2 | experimental | samples / normalized | channel pair linear correlation | per P2 task |
| gcc_phat | GCC-PHAT时延观察 | correlation | P2 | experimental | samples (delay observation) | channel pair PHAT correlation | per P2 task |
| spectral_flux | 谱结构变化 | events | P2 | experimental | FS^2 delta | spectral history | per P1 carousel |
| spectrum_freeze | 频谱冻结和A/B | spectrum | P2 | experimental | stored spectrum + ratio | analysis statistics A/B | per P1 carousel |
| relative_limit | 相对限值检测 | spectrum | P2 | experimental | ratio vs limit | analysis statistics A/B | per P1 carousel |
| cepstrum | 实倒谱 | frequency | P2 | experimental | real cepstrum | P2 chain | per P2 task |
| spectral_kurtosis | 谱峭度有限原型 | frequency | P2 | experimental | kurtosis prototype | P2 spectrum | per P2 task |
| spatial_grid | 球面网格 | spatial | P2 | experimental | unit sphere grid | shared FFT | per P2 task |
| spatial_peaks | 空间图局部峰辅助 | spatial | P2 | experimental | local peaks (assist only) | spatial map | per P2 task |
| room_decay | EDT/T20/T30 | room | P2 | experimental | EDT/T20/T30 seconds | impulse response capture | per P2 task |
| relative_insulation | 相对隔声 | weighting_stats | P2 | experimental | relative band difference | two measurement positions | per P2 task |
| stipa_experimental | 实验STIPA | room | P2 | experimental | uncalibrated STIPA prototype | captured dual trace + finite stage graph | staged high-cost graph |
| noise_rating | NC/NR估计 | room | P2 | experimental | NC/NR relative prototype | third-octave levels | per P2 task |
| room_clarity | C50/C80/D50 | room | P2 | experimental | C50/C80/D50 | impulse response | per P2 task |
| spectral_decay | 分频衰减数据 | room | P2 | experimental | per-band decay data | impulse response | per P2 task |

## 状态判定规则

- available requires actual backend/firmware support AND acceptance evidence; none of the 52 rows qualifies today
- experimental = PL microprogram-native values validated, whole-service RTL/board not accepted
- not_ready = live path needs physical capture or real board link not yet accepted
- unsupported = removed by user (automatic DOA / XYZ / auto source count / trackId)

详细证据（缺失项/共享依赖/整机验收）见 FEATURE_CATALOG.json 的 features[].evidence。
