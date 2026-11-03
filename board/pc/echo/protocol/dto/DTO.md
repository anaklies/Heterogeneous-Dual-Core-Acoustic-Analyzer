# PC 后端 DTO（数据模型）冻结说明

版本：pc-backend-dto v1（2026-10-24 冻结）。与 sixmic-analysis v1 同步演进；字段只增不删，
单位/含义不得单方面改变。机器可读定义：../schema/dto.schema.json。

## 0. 通用规则

- **64 位整数**（采样序号、connectionEpoch、设备单调纳秒、eventId、job 计数）在 Python
  内部为 `int`，在 JSON/TOML/QML 边界一律为十进制字符串。QML/JS 侧不得用 double 承载。
- **32 位字段**（frameId、configVersion、word 值、故障位）为 Python int（0..2^32-1）/
  JSON number。
- **不适用字段用 null，不用 0 伪装有效**。有效性与数值分开：`validity` 对象或
  `*Valid` 布尔。
- 每条测量必须携带来源与身份：`sourceKind`（`pl-live` | `file-replay` |
  `offline-reference` | `test-fixture`）、`deviceId`、`connectionEpoch`、
  `sessionId`、`frameId`、`configVersion`、`sampleIndex`、
  `sampleRateHz`（真实浮点值，非整数取整）、`units`、`quality`。
- Live 模式不得静默回退为 fixture/演示数据：无数据即无数据，状态为 `no_link`。
- 波形/频谱/瀑布的绘制样式不属于 DTO；DTO 只给可解释数据、范围、单位、状态。
- 大数组不内联进 JSON：用 buffer 句柄（见 §12 BufferRef）。QML 只拿到带显式
  `displayOnly` 标记的视窗抽取，原始数据与分析指标保留在数据仓库。

## 1. DeviceInfo

| 字段 | 类型 | 说明 |
|---|---|---|
| deviceId | str | 网关/设备稳定 ID（非 MAC） |
| firmwareId | u32 | 板级固件 ID（0x82000001 候选） |
| hardwareProtocolVersion | int | 板级 MMIO 协议 = 3 |
| gatewayVersion | str | PS 网关版本 |
| networkProtocolVersion | int | 1（sixmic-analysis） |
| connectionEpoch | u64str | 当前纪元 |
| sampleRateHz | float/null | 来自 result word31 的 float32；无结果为 null |
| boardBaseAddress | str/null | 候选 0x43C20000；未确认时 null |
| capabilities | Capabilities | 见 §2 |
| verifiedOnBoard | bool | 是否有实板验收证据；当前必须 false |

## 2. Capabilities

`gateway`：`{version, controlPort, binaryPort, maxBinaryPayloadBytes, maxPendingJobs,
supportedStreams:[str], startedMonotonicNs}`

`device`：每个能力值为 `available` | `experimental` | `not_ready` |
`unsupported`，或布尔（等价 available/not_ready）：

| 字段 | 当前期望值 | 说明 |
|---|---|---|
| livePcm | not_ready | PL raw ring 的 PS 游标/租约/带宽未验收 |
| liveResults | not_ready | 实板结果读取未联调；RTL 分阶段证据不等于整机 |
| resultSnapshotProtocol | 3 | 板级协议号 |
| serviceSnapshots | [] | 实际可读服务列表；当前空 |
| eventCapture | not_ready | 事件采集链路未整机验收 |
| eventDownload | not_ready | 依赖 spool+ack 链路 |
| rawRecording | not_ready | 依赖 livePcm |
| profileUpload | not_ready | profile_upload.c 审查问题未关闭 |
| profileActivate | not_ready | 同上 |
| taskControl | not_ready | P1/P2 启动未实板验收 |
| sensorSnapshot | not_ready | 传感器未实物验收 |
| deviceLog | available | 网关本地日志白名单读取 |
| configCommit | not_ready | 配置提交未实板验收 |
| configVersion | u32 | 实际 active 版本（无设备时 0） |
| protocol3 | bool | 是否成功识别板级协议 3 |
| missing | [str] | 具体缺口文本（文件/字段级） |

能力状态判定规则：`available` 必须有实际后端/固件支持并有验收证据；只有工厂函数/
RTL 模块存在不能打开。`unsupported` 用于用户已取消能力（自动 DOA/SRP-DNN/MUSIC 自动
定位/XYZ 测距/自动源数/trackId）。

## 3. ConnectionState

| 字段 | 类型 | 说明 |
|---|---|---|
| state | enum | disconnected / connecting / handshaking / connected / degraded / reconnecting / failed |
| host, controlPort, binaryPort | | 当前连接参数 |
| deviceId | str/null | hello 后 |
| connectionEpoch | u64str/null | hello 后 |
| sessionId | str/null | hello 后 |
| controlHeld | bool | 是否持有控制权 |
| controlExpiresInMs | int/null | 租约剩余 |
| reconnectAttempt | int | 有界退避次数 |
| lastError | ErrorInfo/null | 最近错误 |
| changedMonotonicNs | u64str | 状态变更本地单调时间 |

reconnect 规则：重连后必须重新 hello、检查 epoch、重新拉能力/状态；不回放旧写命令。

## 4. LiveFrame（结果快照帧）

| 字段 | 类型 | 说明 |
|---|---|---|
| sourceKind | enum | pl-live / file-replay / test-fixture |
| deviceId, connectionEpoch, sessionId | | 身份 |
| frameId | u32 | 结果 word2 |
| configVersion | u32 | 结果 word3 |
| sampleIndex | u64str | word8/9 合成为 u64 |
| sampleRateHz | float | word31 float32 |
| deviceMonotonicNs | u64str/null | 未知为 null 且 deviceTimeValid=false |
| receivedMonotonicNs | u64str | PC 接收单调时间（只用于本地新鲜度） |
| algorithmId, faults | u32 | word1 / word10 |
| words | [u32 x32] | 原始快照（权威） |
| decoded | ResultDecoded | 见 §5 |
| validity | {stale:bool, epoch:int, sampleIndexValid:bool, deviceTimeValid:bool, consistent:bool} | 一致性由 epoch/发布头规则判定 |
| quality | {overwritten:u32, missedWindows:u32, droppedSamples:u32, failedFrames:u32} | 覆盖/丢失计数 |

stale 规则由后端按真实 sampleRate 与设备时间/本地时间差判断；FAST/SLOW 等时间常数功能
必须用连续原始样本，跳帧时置 invalid 并给出原因，不得静默接续。

## 5. ResultDecoded（来自结果 32 字；保持原始码）

`{sensors:SensorSnapshot|null, faults:{bits:u32, recorder:bool, lostEvent:bool,
handoffDrop:bool, sensorAggregate:bool, configRejected:bool, epochOverflow:bool,
pipelineDetailBits:[u32...]}, micStatus:u32, fftBaseWords:u32|null, cycles:u32|null,
slot:u32, backgroundDone:u32, failedFrames:u32}`

## 6. SensorSnapshot

| 字段 | 类型 | 说明 |
|---|---|---|
| temperatureC | float/null | word17 有符号摄氏×100 |
| humidityRaw | u32/null | word18 SHT 原始码，**不是百分数**；未校准不换算 |
| pressurePa | u32/null | word19 |
| soundSpeedMps | float/null | word20 float32 |
| valid | {temperature, pressure, pose, soundSpeedModel:bool} | word21 bits0..3 |
| environmentMode | u8/null | word21 bits5:4 |
| poseRaw | {roll,pitch,yaw,qw,qx,qy,qz:int|null} | word22..25 原始 int16 |
| imuScaleStatus | str | `unverified`（未确认 IMU 型号/比例/姿态约定前永远不当作实测姿态） |
| sensorErrors | u16 | word28 bits15:0 |
| sensorFaults | u8 | word28 bits23:16 |
| envSequence, poseSequence | u32 | word26/27 |
| deviceMonotonicNs | u64str/null | 有真实设备时间才填 |

## 7. AudioChunk

| 字段 | 类型 | 说明 |
|---|---|---|
| sourceKind, deviceId, connectionEpoch, sessionId | | 身份 |
| streamId | u32 | 二进制流 |
| firstSampleIndex | u64str | 首记录 sampleIndex |
| sampleCount | int | 记录条数 |
| channels | int | 6 |
| channelOrder | [str] | mic1..mic6（顺序即 PL 通道顺序） |
| sampleFormat | str | `int24-le-signextended-in-int32` |
| sampleRateHz | float | 真实浮点采样率 |
| units | str | `digital full scale (24-bit PCM codes)`；不称 dB SPL |
| records | BufferRef | 32 字节/条，不展开成 QVariantList |
| gapBefore | bool | 与前一帧之间有已知缺口 |
| continuity | {continuous:bool, expectedFirstSampleIndex:u64str|null, gaps:[...]} | 录制消费者必须检查 |
| deviceMonotonicNs | u64str/null | 采集时间（未知 null） |

## 8. SpectrumFrame

| 字段 | 类型 | 说明 |
|---|---|---|
| sourceKind, deviceId, connectionEpoch, sessionId | | 身份 |
| frameId, configVersion, sampleIndex | | 身份 |
| serviceId | str | 产生该谱的服务（resultWords/服务快照） |
| spectrumKind | enum | fft-magnitude / psd-welch / stft-frame / octave-band / das-map |
| fftSize | int | 2048（STFT 候选） |
| binCount | int | 1025（0..Nyquist） |
| window | str | hann-2048（由 PL/服务 metadata 提供，不得 PC 猜） |
| scaling | str | 例 `FS-squared-per-bin` / `FS-squared-per-Hz` |
| frequencyAxis | {firstBinHz:float, binWidthHz:float, sampleRateHz:float} | 不得硬编码 48000 |
| units | str | FS²/bin 等；不称 dB SPL |
| values | BufferRef | float32 LE 连续 buffer |
| validity | {stale:bool, gapBefore:bool, sourceFramePresent:bool} | |
| displayOnly | bool | false=测量数据；true=视窗抽取仅供绘制 |
| algorithmVersion | str/null | 未报告即 null |

## 9. ServiceResult

| 字段 | 类型 | 说明 |
|---|---|---|
| serviceId, descriptor | str/int | 服务身份 |
| slot | u32 | 槽位 |
| session, config, generation | u32 | 必须匹配期望；不匹配拒绝使用 |
| programVersion | u32 | 服务程序版本 |
| sourceFrame | u32 | 执行帧 |
| sampleIndex | u64str/null | 发布头 word7/8 |
| units | str/null | 服务 metadata 单位 |
| words | BufferRef | 原始输出字（uint32） |
| decoded | object/null | 按服务 metadata 解码（字段名/比例来自 PL profile，不在 PC 猜测） |
| validity | {done:bool, error:u32, headerConsistent:bool, provenanceValid:bool} | headerConsistent 需前后 16 字完整比较 |
| provenance | {kind, inputRecordIds:[u64str], note} | 离线输入必须另附 recordId/采集 provenance，不混为同一来源 |

## 10. EventRecord

| 字段 | 类型 | 说明 |
|---|---|---|
| eventId | u64str | 网关分配稳定 ID |
| deviceId, connectionEpoch, sessionId | | 身份 |
| capturedFirstSampleIndex, capturedLastSampleIndex | u64str | 采样边界（非 UTC） |
| frames | u32 | 记录条数 |
| sampleRateHz | float | 真实浮点采样率 |
| clipReason | u32 | 原始算法原因位；**不做声源分类** |
| flags | {incomplete, lostEvents, summaryStale, envInvalid, poseInvalid:bool} | 必须保存并上报 |
| preQ22, postQ22, deltaQ22, summaryAgeSamples, summaryValid | | clip word12..15 原始/解码 |
| bank, offsetBytes | int | PS 侧位置（PC 不直接使用地址） |
| file | {totalBytes:u64str, sha256:str, state:missing/downloading/stored/verified} | 容器 SMC1 v1 |
| ack | {acked:bool, duplicate:bool, ackedMonotonicNs:u64str|null} | 只有 PC 落盘+hash 校验后才 ack |
| manifestPath | str/null | PC 事件 manifest 绝对路径 |
| sourceKind | enum | 必须如实 |

## 11. JobState

`{jobId:str, kind:str, state:accepted|running|cancel_requested|completed|failed|canceled,
progress:float|null, createdAtMonotonicNs:u64str, updatedAtMonotonicNs:u64str,
clientTaskKey:str|null, requestId:str, result:object|null, error:ErrorInfo|null,
cancelRequested:bool, cancelAcknowledged:bool}`

`accepted` 不是完成；只有 `completed|failed|canceled` 是终态。
`cancel_requested` 表示请求已受理、尚未在安全边界停止。

## 12. BufferRef（大数组句柄）

`{handleId:str, bytes:u64str, elementType:"int32"|"uint32"|"float32"|"uint8", count:int,
layout:"interleaved"|"planar", alignment:int, displayOnly:bool, sourceKind:str,
sha256:str|null}`

生命周期：handle 由数据仓库（DataStore）拥有；QML/适配层只能通过
`readSlice(handleId, offset, count)` 获取有界视图或临时 QByteArray，不得把整块大数组
转换成 QVariantList 塞进 GUI 信号。析构/淘汰由仓库引用计数管理，UI 不得长期持有裸指针。

## 13. ErrorInfo

`{code:str, messageKey:str, retryable:bool, detail:object, occurredMonotonicNs:u64str}`
错误码见 ../errors/ERROR_CATALOG.json。UI 只用 messageKey 翻译 + 可选技术 detail，
不得只显示错误数字。

## 14. RecordingManifest

| 字段 | 类型 | 说明 |
|---|---|---|
| recordingId | str | 录制 ID |
| format | str | `smc-recording-v1` |
| deviceId, connectionEpoch, sessionId | | 身份 |
| sourceKind | enum | 录制来源，禁止把 fixture 录成 pl-live |
| startedMonotonicNs, stoppedMonotonicNs | u64str | |
| channels, sampleFormat, units | | 6 / int24-le-signextended-in-int32 / FS codes |
| realSampleRateHz | float | 真实浮点采样率（例如 48009.775390625） |
| integerRateHz | int | WAV/播放用整数率（例如 48010） |
| rateRoundingErrorHz | float | integerRateHz - realSampleRateHz，必须记录 |
| records | u64str | 记录条数 |
| firstSampleIndex, lastSampleIndex | u64str | 采样序号范围 |
| segments | [{path, bytes:u64str, sha256, firstRecord:int, recordCount:int}] | 分段原始文件 |
| wav | {path, sha256, integerRateHz, realSampleRateHz, channelCount, bitsPerSample} | 六通道 24-bit PCM |
| gaps | [{reason, firstMissingSampleIndex:u64str, lastMissingSampleIndex:u64str, droppedRecords:u64str}] | 缺口不得压缩成连续音频 |
| flags | {incomplete, lostEvents, summaryStale, envInvalid, poseInvalid:bool} | |
| algorithmVersions | {resultProtocol:int, algorithmId:str, servicePrograms:{}} | |
| notes | [str] | 质量说明（未实板、非 dB SPL 等） |
| sha256 | str | manifest 规范化 JSON 的 sha256（自校验） |
