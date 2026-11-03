# sixmic-analysis v1 网络协议（冻结）

状态：**冻结草案 FROZEN-1（2026-10-24）**。本文是本轮新增网络协议的唯一定义。它
不是旧版 TCP 48110 定位遥测协议的替代或扩展：旧服务保持原样，新服务独立实现。
实现方为：
- PC 端：C:/Users/sunxi/Desktop/sixmic3D/apps/sixmic-desktop/backend/
- PS 网关候选：C:/Users/sunxi/Desktop/sixmic3D/deployment/ps_analysis_gateway/
- 共享 C 常量：C:/Users/sunxi/Desktop/sixmic3D/interfaces/pc_backend_v1/c/sixmic_analysis_wire.h
- 机器可读 schema：C:/Users/sunxi/Desktop/sixmic3D/interfaces/pc_backend_v1/schema/
- golden wire 样例：C:/Users/sunxi/Desktop/sixmic3D/interfaces/pc_backend_v1/golden/

协议名 `sixmic-analysis`，版本 `1`。它**不是**硬件 MMIO 协议版本：板级寄存器接口是
协议 3（见 `device/MMIO_PROTOCOL3.md`），两者分别记录，禁止混用版本号。

## 0. 真实性约束（协议层强制）

1. 本协议当前候选实现**未完成实板联调**。任何一方不得把 fixture/回放数据标成
   `pl-live`。`sourceKind` 必须如实标记：`pl-live` / `file-replay` / `test-fixture`。
2. live PCM 能力默认 `not_ready`：`capabilities.device.livePcm = false`。没有实板
   采集验收前不得置 true。
3. 禁止远程 shell、任意物理内存读写、任意文件路径写入。所有命令都是白名单操作；
   未知 op 返回 `unknown_op`。
4. 时间：`deviceMonotonicNs` 为设备单调时钟纳秒。设备无法提供时置 0 且清除
   `SMA_FLAG_DEVICE_MONOTONIC_VALID`；接收方不得用 PC 接收时间顶替采集时间。
5. 64 位计数器（采样序号、connectionEpoch、设备时间）在 JSON 中一律为**十进制字符串**，
   在内部为整数（uint64）。QML/JavaScript 不得直接持有这些值做数学运算。

## 1. 传输

| 通道 | 默认端口 | 用途 |
|---|---|---|
| control | TCP 48120 | UTF-8 JSON Lines：握手、能力、状态、控制、任务、事件通知 |
| binary | TCP 48121 | SMA1 定长 64 字节头 + 二进制负载：PCM / 结果字 / 服务快照 / 事件文件块 |

两端端口均可配置（配置文件或启动参数），默认值固定为 48120/48121，**不得**占用旧
48110。PS 侧监听地址必须由实际网口/路由确认后指定，不得假定网口名 eth0。

连接拓扑：PS 网关是 TCP 服务端，PC 是客户端。物理链路固定为 PS 以太网口 ↔ 网线/
交换机 / USB 转网口 ↔ Windows PC；**不使用 PL 网口**，不增加 PL MAC、网络协议栈或
FPGA 网络硬件。

## 2. 控制通道（JSON Lines）

### 2.1 分帧
- 每帧一行 UTF-8 文本，以单个 0x0A 结束。禁止 0x0D（收到即视为非法帧，见 2.8）。
- 单行上限 65536 字节（含行尾 LF）。超限立即返回错误并关闭连接（不尝试继续同步）。
- 发送方不得输出空行；接收方忽略空行并计数 emptyLines。
- 半包/粘包由接收方按字节流切分处理；一次 read 可能拿到多行或半行。
- 深度上限 32 层，单帧节点上限 20000。超出 → `bad_json`。
- 重复键 → `bad_json`。NaN/Infinity → `bad_json`。非法 UTF-8 → `bad_utf8` 并
  关闭连接（不允许猜测帧边界继续同步）。

### 2.2 请求
~~~json
{"protocol":"sixmic-analysis","version":1,"requestId":"c-000001","sessionId":"sess-7f3a","op":"status.get","args":{}}
~~~
- `protocol` 必须等于 `sixmic-analysis`，否则 `protocol_mismatch`。
- `version` 必须等于 1（整数），否则 `unsupported_version`。
- `requestId`：1..64 个字符，字符集 A-Za-z0-9._:-，同一会话内唯一。重复 requestId
  在同一会话内去重：返回首次结果（缓存 256 条 / 120 秒），不重复执行。
- `sessionId`：除 `hello` 外必须等于服务端分配的当前会话；不等 → `unknown_session`。
- `op`：白名单（见第 4 节）。
- `args`：对象；无参数用 `{}`。
- 未知顶层字段忽略（向前兼容）；未知 op 拒绝；args 中必填缺失按 schema 拒绝。

首个请求必须是 `hello`；否则 `not_authenticated`。

### 2.3 响应
~~~json
{"type":"response","protocol":"sixmic-analysis","version":1,"requestId":"c-000001","status":"ok","result":{}}
{"type":"response","protocol":"sixmic-analysis","version":1,"requestId":"c-000002","status":"accepted","result":{"jobId":"job-0000000007"}}
{"type":"response","protocol":"sixmic-analysis","version":1,"requestId":"c-000003","status":"error","error":{"code":"not_ready","messageKey":"errors.not_ready","retryable":false,"detail":{"feature":"livePcm"}}}
~~~
- `status` ∈ `ok` | `accepted` | `error`。
- `ok`：请求已完成，`result` 为最终结果。
- `accepted`：长任务已被接受，**不是完成**。`result.jobId` 存在；完成/失败/取消通过
  `jobUpdated` 通知与 `job.get` 查询。禁止把 accepted 当成功完成展示。
- `error`：`error.code` 为稳定机器码（ERROR_CATALOG.json），`messageKey` 供 UI 翻译，
  `detail` 携带可追踪技术信息（不得含密钥/白名单外路径数据）。

### 2.4 服务端通知
~~~json
{"type":"event","protocol":"sixmic-analysis","version":1,"event":"jobUpdated","eventId":"12","data":{}}
~~~
事件枚举（版本 1 冻结）：
| event | data |
|---|---|
| jobUpdated | JobState |
| eventAdded | EventRecord（新事件已在本机 spool 落盘） |
| deviceState | {state, reasons:[str], connectionEpoch, sinceMonotonicNs} |
| configApplied | {version, applied:bool, rejected:bool, rejectedReason?:str} |
| recordingChanged | {recordingId, state, records, bytes, gaps} |
| streamGap | STREAM_GAP 的 JSON 等价体（控制通道副本，可丢） |
| diagnosticAdded | {level, code, messageKey, detail, monotonicNs} |
| controlChanged | {held:bool, owner?:str, expiresInMs?:int} |

通知可合并/丢弃（控制通道通知不承担数据完整性）。数据完整性只由 binary 通道保证。

### 2.5 会话与连接纪元（connectionEpoch）
- PS 网关每次进程启动分配新的 connectionEpoch（uint64 十进制字符串），持久化递增，
  重启后必须变化。epoch 变化即旧会话/旧 binary token/旧 ACK 全部失效。
- hello 返回服务端分配的 sessionId。PC 必须用它填充后续请求；重连后必须重新 hello，
  查询能力与实际状态，**不得无条件重放旧写命令或重复触发任务**。
- 控制连接断开不会重置 PL，不会擦除采集，不会破坏仍被租用的事件数据。
- heartbeat：客户端发送 {"op":"heartbeat","args":{}}，服务端回 status:"ok",
  result:{"serverMonotonicNs":"..."}。

### 2.6 幂等与去重
- 同一会话内重复 requestId 返回首次响应。
- event.ack 幂等：同一 eventId+sha256 重复 ack 返回 duplicate:true，不报错。
- task.start 的 params 中可带 clientTaskKey（≤64 字符）用于客户端重试去重：同 key
  在 120 秒内返回同一 jobId。

### 2.7 超时与限流
- 同步 op 默认 5 秒内响应；服务端对无法立即判定的长操作必须 accepted＋jobId。
- 每连接请求限速 64 次/秒（突发 128）；超出返回 busy（可重试），不静默丢弃。
- 控制连接空闲 120 秒无任何帧 → 服务端关闭。
- 控制权租约默认 30 秒，客户端须在 ≤ 租约/2 的间隔 control.renew。

### 2.8 非法输入处理
| 情况 | 处理 |
|---|---|
| 超长行（>65536B） | error.code=line_too_long，关闭连接 |
| 非法 UTF-8 | error.code=bad_utf8，关闭连接 |
| 非法 JSON/重复键/NaN/超深度 | bad_json，丢弃该行并保持连接（无法重新同步则关闭） |
| 未知版本 | unsupported_version，保持连接 |
| 未知 op | unknown_op，保持连接 |
| 参数类型/范围错误 | bad_args，保持连接，detail.field 指出字段 |
| 越界/非法状态 | bad_state 或 rejected，保持连接 |
| 未知协议名 | protocol_mismatch，关闭连接 |

## 3. 控制权仲裁（单一控制者）

- 板上有且只有一个设备控制者。PC 与未来 PS 触摸屏经同一个 PS 控制仲裁器访问 PL。
- control.claim 成功后返回随机 controlToken（32 hex 字符）。写配置/任务/录制/profile
  操作必须携带有效 token；观察者只读（status/subscribe/event.list）。
- 同一时刻只能有一个持有者；已被持有时 control.claim 返回 control_conflict，
  detail.holder 给出占用方名称与开始时间（不泄露 token）。
- 断连、心跳超时、租约过期 → 释放控制权：停止接受新的 P2 工作，排空已接受事务，
  **不重启 PL、不擦除采集、不破坏租用中的事件数据**。
- control.release 显式释放。token 错误 → bad_token。

## 4. 白名单操作（v1）

`hello` 除外的所有 op 都需要 sessionId；标注 **C** 的 op 需要有效 controlToken。
参数/结果中 u64 均写成十进制字符串。

### 4.1 会话与状态
| op | args | result |
|---|---|---|
| hello | {clientName, clientVersion, maxBinaryPayloadBytes?} | 见 4.2 |
| capabilities.get | {} | {device:DeviceCapabilities, gateway:{...}} |
| status.get | {} | StatusSnapshot（见 4.3） |
| diagnostics.get | {tailLines?:1..2000} | {deviceLog:[str], logDropped:"<u64>", queues:{...}, uptimeSeconds, gatewayVersion, faults:u32} |
| heartbeat | {} | {serverMonotonicNs:"<u64>"} |

### 4.2 hello 结果
~~~json
{
  "protocol":"sixmic-analysis","protocolVersion":1,"serverVersion":"ps-gw-0.1.0",
  "deviceId":"sixmic-dev-0001","connectionEpoch":"3","sessionId":"sess-0003-01",
  "limits":{"maxLineBytes":65536,"maxBinaryPayloadBytes":1048576,
            "maxPendingJobs":64,"duplicateCacheSeconds":120,"maxControlLeaseSeconds":300},
  "capabilities":{"device":{},"gateway":{}},
  "config":{"activeVersion":10,"pending":false,"shadowDirty":false},
  "control":{"held":false}
}
~~~

设备能力（device）字段（v1 冻结；值为布尔或枚举，未知/未验收必须 false/not_ready）：
~~~json
{"livePcm":false,"liveResults":false,"resultSnapshot":"not_ready","serviceSnapshots":[],
 "eventCapture":false,"eventDownload":false,"rawRecording":false,"profileUpload":false,
 "profileActivate":false,"taskControl":false,"sensorSnapshot":false,"deviceLog":true,
 "configCommit":false,"configVersion":0,"protocol3":false,
 "missing":["PS gateway not integrated on a real board",
            "PL raw ring PS consumer/lease and full bandwidth NOT accepted"]}
~~~
capabilities.device.liveResults 只有在实板结果读取验收后才可为 true；
serviceSnapshots 列出实际可读服务（当前为空数组）。字段 missing 记录未打通原因，
必须与实际固件/网关状态一致，不得为打开 UI 而写 true。

### 4.3 StatusSnapshot（完整 schema 见 schema/status.schema.json）
~~~json
{"connectionEpoch":"3","sessionId":"sess-0003-01","deviceState":"ready",
 "deviceStateReasons":[],
 "control":{"held":false,"expiresInMs":null},
 "config":{"activeVersion":10,"shadowVersion":10,"pending":false,"lastRejectedVersion":null},
 "resultFreshness":{"frameId":1234,"configVersion":10,"sampleIndex":["0","12345678"],
                    "deviceMonotonicNs":null,"receivedMonotonicNs":"1700000000000000000","stale":false},
 "sensors":null,
 "faults":{"faultBits":0,"sensorErrors":0,"microphoneStatus":0,"missedWindows":0,
           "droppedSamples":0,"lostEvents":0,"handoffDrops":0},
 "queues":{"pcmPendingBytes":"0","pcmDroppedBytes":"0","resultDroppedFrames":"0",
           "eventSpoolBytes":"0","eventSpoolLimitBytes":"67108864"},
 "recording":{"recordingId":null,"state":"idle"},
 "jobs":{"pending":0},
 "pl":{"resultWordProtocol":3,"algorithmId":"0x82000002","capabilities":"0"}}
~~~

### 4.4 控制权
| op | args | result |
|---|---|---|
| control.claim **C** | {leaseSeconds?:5..300} | {controlToken,expiresInMs,owner:{clientName,sinceMonotonicNs}} |
| control.renew **C** | {controlToken} | {expiresInMs} |
| control.release **C** | {controlToken} | {released:true} |

注：claim 自身不要求已有 token，但由请求方在 args 中不带 token；renew/release 必须带 token。

### 4.5 订阅与二进制流
| op | args | result |
|---|---|---|
| subscribe | {streams:[{type,streamName?,filter?}],deliverSchema:true} | {subscriptionId,streams:[{streamId:u32,type,schemaSha256}]} |
| stream.open | {subscriptionId} 或 {eventId} | {binaryToken,port,maxPayloadBytes,expiresInMs,streams:[...]} |
| stream.close | {streamId} | {closed:true} |
| unsubscribe | {subscriptionId} | {unsubscribed:true} |

type ∈ resultWords | pcmRecord32 | serviceSnapshot | events | eventFile。
未实现的流类型必须返回 not_ready（例：live PCM 未打通时 pcmRecord32 不可订阅，
detail 写明 missing:"PL raw ring PS consumer/lease not accepted"）。
每个 binary 连接必须先收到 STREAM_SCHEMA 才能解释后续数据；没有 schema 的裸数组一律拒绝。

### 4.6 配置（32 字影子 + 提交 + 应用确认）
| op | args | result |
|---|---|---|
| config.read | {} | {shadow:[32 u32],active:[32 u32],activeVersion:u32,pending:bool} |
| config.write **C** | {words:[{index:0..31,value:u32}]} | {shadowDirty:true}（仅影子，不提交） |
| config.commit **C** | {version:u32,words:[32 u32]?} | accepted + jobId；随后 configApplied 通知 {version,applied:true} 或 {rejected:true,rejectedReason} |
| config.abort **C** | {} | {aborted:true}（撤销未提交影子） |

规则：
- version 必须唯一递增且 ≠ 当前 active 版本；重复/回退版本 → rejected。
- 只写影子不等于生效；只有 configApplied.applied=true 才算应用。
- 32 字布局见 device/MMIO_PROTOCOL3.md；DDR 地址/长度以字节计，arena_words/
  descriptor 索引以 32-bit 字计，不得混淆。
- 配置字段做白名单范围校验（分区不重叠、ring 容量/对齐、descriptor 索引等）；
  任何越界在写 PL 之前拒绝，不得让 PL 拒绝对外表现成成功。

### 4.7 任务
| op | args | result |
|---|---|---|
| task.start **C** | {kind:"p1Carousel"\|"p2OneShot",params?,clientTaskKey?} | accepted+jobId |
| task.cancel **C** | {jobId} | {cancelRequested:true}（不是已取消；最终看 jobUpdated） |
| job.get | {jobId} | JobState |
| job.list | {cursor?,limit?:1..100} | {jobs:[JobState],nextCursor?} |

取消语义：只有 PL/网关在实际安全边界停止后才 state="canceled"；期间为
cancel_requested。accepted、cancel_requested 都不是完成。

### 4.8 录制
| op | args | result |
|---|---|---|
| recording.start **C** | {streams:["pcmRecord32"],maxBytes?,maxSeconds?} | {recordingId,startedMonotonicNs,state:"recording"} |
| recording.stop **C** | {} | {recordingId,state:"stopped",records:"<u64>",bytes:"<u64>",gaps:int,sha256} |
| recording.status | {} | {recordingId,state,records,bytes,gaps,queueDrops} |

录制是端到端连续性确认：出现 gap 必须写入 manifest（STREAM_GAP），不得把缺帧
压缩成连续音频。实时图可只保最新帧；录制消费者单独确认连续性。

### 4.9 事件
| op | args | result |
|---|---|---|
| event.list | {cursor?,limit?:1..200} | {events:[EventRecord],nextCursor?} |
| event.get | {eventId} | {event:EventRecord,file:{totalBytes,sha256,chunkBytes}} |
| event.download | {eventId,offset?:"0",maxBytes?} | {streamId,chunkBytes,totalBytes,sha256,offset}（随后 binary EVENT_FILE_CHUNK） |
| event.ack | {eventId,sha256} | {acked:true,duplicate:bool} |
| event.discard **C** | {eventId,reason} | {discarded:true}（仅无容量时显式丢弃，记录 lost 原因） |

PC 写盘成功并校验 sha256 后才 event.ack；PS 收到匹配 ack 才允许释放对应事件数据
（本地 spool 与/或 clip bank）。相同 eventId 重复传输幂等。

### 4.10 profile（默认未开放）
profile.upload / profile.activate / profile.deactivate 在 v1 返回
error.code="not_ready"，detail 说明 profile_upload.c 两遍读取期间文件变化可绕过
第二遍边界检查的审查问题未关闭。网关不得提供任意文件写路径。

## 5. 二进制通道（SMA1）

### 5.1 头（固定 64 字节，全部小端，显式编码）
| 偏移 | 类型 | 字段 | 说明 |
|---|---|---|---|
| 0 | u8[4] | magic | 'S','M','A','1' |
| 4 | u16 | protocolVersion | 1 |
| 6 | u16 | headerBytes | 64 |
| 8 | u16 | messageType | 见 5.3 |
| 10 | u16 | flags | 见 5.2 |
| 12 | u32 | payloadBytes | ≤ 协商上限；与类型匹配 |
| 16 | u32 | streamId | 0=连接级（HELLO/ACK/HEARTBEAT/BYE/ERROR） |
| 20 | u32 | sequence | 每流递增，mod 2^32 |
| 24 | u64 | connectionEpoch | 必须等于当前纪元 |
| 32 | u64 | firstSampleIndex | PCM/结果的有效性由 flag 指示 |
| 40 | u64 | deviceMonotonicNs | 未知时 0 且清 flag |
| 48 | u32 | frameId | 结果帧号；不适用 0 |
| 52 | u32 | configVersion | 不适用 0 |
| 56 | u32 | payloadCRC32 | IEEE 反射 CRC-32（0xEDB88320/init 0xFFFFFFFF/xorout 0xFFFFFFFF），仅负载 |
| 60 | u32 | reserved | 必须 0 |

### 5.2 flags
| bit | 名称 | 语义 |
|---|---|---|
| 0 | CRC32_VALID | payloadCRC32 有效（负载非空时必须为 1） |
| 1 | GAP_BEFORE | 本帧之前该流有已知缺口（另有 STREAM_GAP 详情） |
| 2 | LAST_CHUNK | 文件传输最后一块 |
| 3 | FIRST_CHUNK | 文件传输第一块 |
| 4 | DEVICE_MONOTONIC_VALID | deviceMonotonicNs 是真实设备时间 |
| 5 | SAMPLE_INDEX_VALID | firstSampleIndex 对该帧有意义 |

bits 6..15 保留，发送方写 0；接收方忽略但计数。头损坏（magic/版本/headerBytes/
reserved/CRC 不符/长度超限）→ **终止该连接**，不允许无界分配或猜测。

### 5.3 消息类型（冻结）

勘误 ERRATUM-1（2026-10-24）：BYE 携带可选 UTF-8 JSON {"reason":...}（见 5.3 表与第 6 节
背压要求），只有 HEARTBEAT 必须为空负载。共享 C 头 sma_header_decode() 早期版本错误地拒绝
BYE 负载（-7），已修正为接受 BYE 负载、仍拒绝 HEARTBEAT 负载；golden/bye_backpressure.bin
（64B 头 + 25B JSON）在修正后应正常解码。协议版本不变（该更正不改变 wire 字节，只纠正解码器）。
| 值 | 名称 | 方向 | 负载 |
|---|---|---|---|
| 0x0001 | HELLO | C→S | UTF-8 JSON {protocol,version,connectionEpoch,token,maxPayloadBytes} |
| 0x0002 | HELLO_ACK | S→C | UTF-8 JSON {accepted,maxPayloadBytes,connectionEpoch,streams:[...]} |
| 0x0003 | STREAM_SCHEMA | S→C | UTF-8 JSON（见 5.4） |
| 0x0004 | PCM_RECORD32 | S→C | N × 32 字节原始记录（见 5.5） |
| 0x0005 | RESULT_WORDS32 | S→C | 128 字节 = 32 × u32 LE |
| 0x0006 | SERVICE_SNAPSHOT | S→C | 16 字发布头 + 服务字（见 5.7） |
| 0x0007 | EVENT_FILE_CHUNK | S→C | 事件文件容器字节区间（见 5.8） |
| 0x0008 | STREAM_GAP | S→C | UTF-8 JSON 缺口记录（见 5.9） |
| 0x0009 | HEARTBEAT | 双向 | 空负载 |
| 0x000A | BYE | 双向 | UTF-8 JSON {reason}，随后关闭 |
| 0x000B | ERROR | S→C | UTF-8 JSON {code,messageKey,detail}，随后关闭 |

未知 messageType：按 payloadBytes 有界读取并丢弃，计数后继续（不得中断连接，除非头本身
不合规）。未知版本、越界长度、错误 CRC 一律关闭连接。

### 5.4 STREAM_SCHEMA（每个流的第一帧，先于任何数据）
~~~json
{"streamId":1,"streamType":"pcmRecord32","sourceKind":"pl-live","deviceId":"sixmic-dev-0001",
 "connectionEpoch":"3","encoding":"sma1","units":"digital full scale PCM24 codes",
 "createdMonotonicNs":"1700000000000000000","simulated":false,
 "pcm":{"channels":6,"channelOrder":["mic1","mic2","mic3","mic4","mic5","mic6"],
        "sampleFormat":"int24-le-signextended-in-int32","recordBytes":32,
        "sampleIndexOffset":24,"sampleIndexEncoding":"uint64-le-low-word-first",
        "sampleRateHz":48009.775390625,"sampleRateSource":"pl-result-word31-float32",
        "recordRateHz":1500.3054,"frameGroupRecords":150,
        "gapPolicy":"explicit STREAM_GAP; never silently splice"},
 "validity":{"deviceTime":"optional","sampleIndex":"required","gapBefore":"flag"}}
~~~
- sourceKind 必须如实：pl-live（实板/实网关实时）、file-replay（读录制文件）、
  test-fixture（确定性测试服务器/样例）。**禁止**把 fixture 标成 pl-live。
- 采样率来自硬件 metadata（当前候选 48009.775390625 Hz），不得硬编码 48000；WAV 导出
  的整数采样率取整误差必须与真实浮点采样率、起始序号一起记录在 manifest。
- resultWords32 的 schema 必须附 wordMap（32 项：index/name/unit/encoding/validity）。
- serviceSnapshot 的 schema 必须附 headerMap（16 项）与 payloadWordCount 规则。
- eventFile 的 schema 必须附 eventId、totalBytes、sha256、chunkBytes、container。

### 5.5 PCM_RECORD32 负载
- payloadBytes % 32 == 0；payloadBytes 至少 32（空负载不合法）。
- 每条记录 32 字节：
  - offset 0..23：6 个**有符号 24-bit PCM**，每个符号扩展后放在小端 int32。
    即 v = (int32)(bytes[4c] | bytes[4c+1]<<8 | bytes[4c+2]<<16);
    if (v & 0x800000) v |= 0xFF000000;
    **不是** 24 字节六通道 float，不能省略符号扩展。
  - offset 24..31：uint64 sampleIndex，低字在前。
- 帧内 sampleIndex 必须逐条 +1；跨帧必须检查 +1 连续性；不连续 → STREAM_GAP 且
  下一帧 GAP_BEFORE=1，接收方不得静默拼接。
- firstSampleIndex = 帧内第一条记录序号，SAMPLE_INDEX_VALID=1。
- 约 1.54 MB/s 为应用负载估算（32B × 48009.775 / 6 约 1.54 MB/s），不是已测网速；
  验收必须报告实测吞吐、缓冲与丢失。

### 5.6 RESULT_WORDS32
- 负载固定 128 字节 = 板级协议 3 的 32 字结果快照（epoch 一致性由 PS 侧保证）。
- 每帧 frameId/configVersion 来自负载 word2/word3；头中字段必须与负载一致，
  不一致 → 该帧丢弃并计数 inconsistentResultFrames。
- deviceMonotonicNs 若对应板级算法时钟可换算则给出并置 flag；否则 0 且清 flag。
- 传感器原始码规则见 device/MMIO_PROTOCOL3.md：湿度 raw 不是百分数；IMU 原始 int16
  比例/姿态约定未确认前标记 unverified；不得把回退值显示为实测。

### 5.7 SERVICE_SNAPSHOT
16 字发布头（LE u32）+ length 个服务输出字：
| 字 | 字段 | 说明 |
|---|---|---|
| 0 | magic | 0x52534C54 |
| 1 | commitSequence | 单调提交序号 |
| 2 | session | 与配置 session 一致 |
| 3 | config | 与配置版本一致 |
| 4 | generation | 程序代次 |
| 5 | programVersion | 服务程序版本 |
| 6 | sourceFrame | 执行帧（离线资料另行记录 recordId/provenance） |
| 7 | sampleIndexLow | 采样序号低字 |
| 8 | sampleIndexHigh | 采样序号高字 |
| 9 | slot | 槽位 |
| 10 | length | 有效输出字数（≤ 分配容量） |
| 11 | descriptor | 描述符索引 |
| 12 | error | 0 表示无错 |
| 13 | pc | 程序计数器（诊断） |
| 14 | done | 1 表示完成 |
| 15 | reserved | 0 |

读取规则（强制）：先复制 16 字头 → 数据 → 再复制 16 字头，完整比较（含 session/config/
generation/commitSequence）；不一致则丢弃/重试。只有 magic 有效、done==1、error==0、
且 session/config/generation 与期望一致时才能使用数据。不能只看旧 DONE 或只比较 slot 计数。

### 5.8 EVENT_FILE_CHUNK 与事件文件容器
下载流：event.download 返回 streamId 后，客户端 stream.open，服务端逐块发送
EVENT_FILE_CHUNK；块内为事件文件容器的字节区间 [offset, offset+payloadBytes)。
sequence 从 0 递增，第一块 FIRST_CHUNK，最后一块 LAST_CHUNK。块大小默认 64 KiB，
上限受 maxBinaryPayloadBytes 约束。

事件文件容器（SMC1 v1，64 字节头 + 原始 32 字节记录流）：
| 偏移 | 类型 | 字段 |
|---|---|---|
| 0 | u8[4] | magic 'S','M','C','1' |
| 4 | u16 | version = 1 |
| 6 | u16 | headerBytes = 64 |
| 8 | u32 | recordBytes = 32 |
| 12 | u32 | channels = 6 |
| 16 | u32 | flags（bit0 incomplete, bit1 lostEvents, bit2 summaryStale, bit3 envInvalid, bit4 poseInvalid） |
| 20 | u32 | clipReason（原始字段，不做声源分类） |
| 24 | u64 | eventId |
| 32 | u64 | firstSampleIndex |
| 40 | u64 | lastSampleIndex |
| 48 | u64 | recordCount |
| 56 | u32 | sampleRateFloat32 bits（真实采样率） |
| 60 | u32 | headerCRC32（覆盖 0..55） |

记录流为解环后的连续记录（PS spool 负责两段 ring 拼接），记录格式同 5.5。manifest 由 PC
另存为 JSON（不塞进容器）：eventId、sha256、字节数、真实浮点采样率、起始序号、缺口列表、
incomplete/lost/stale 标志、来源、采集 provenance、创建时间。

### 5.9 STREAM_GAP
~~~json
{"streamId":4,"reason":"queue_overflow","droppedRecords":"150","firstMissingSampleIndex":"1234500",
 "lastMissingSampleIndex":"1234649","detectedDeviceMonotonicNs":null,"sourceKind":"pl-live"}
~~~
reason ∈ queue_overflow | network_drop | spool_full | spool_lost | recording_discontinuity
| pl_dropped | epoch_change | unknown。缺口必须显式上报并写入录制 manifest，禁止静默压缩。

## 6. 队列、背压与丢失
- 控制/数据队列分离。网络慢端、磁盘慢端、PC 断线不得阻塞 PL 采集。
- 所有队列有上限（控制 pending ≤64 jobs；PCM 待发 ≤8 MiB；事件 spool ≤64 MiB 默认）。
- 溢出必须计数（pcmDroppedBytes、resultDroppedFrames、eventSpoolDropped）并可查询；
  实时图优先保最新帧；完整录制单独确认连续性，不能静默丢样。
- 单 binary 连接发送积压超过上限时服务端必须 disconnect（发送 BYE {reason:"backpressure"}）
  而不是无界缓存。

## 7. 重连
- 有界退避（示例 0.5,1,2,4,8 秒，上限 15 秒，带抖动）。
- 重连后：hello → 检查 connectionEpoch → capabilities.get → status.get →
  重新 subscribe。不得自动重放旧配置提交/旧任务；旧 epoch 的结果、ACK、事件块一律拒绝。
- 控制权不跨连接继承：重连后需重新 control.claim（若原租约已过期）。

## 8. 错误码
稳定机器码见 errors/ERROR_CATALOG.json（含 messageKey、可重试性、scope）。
scope=control 的错误码用于控制通道响应；二进制通道的 ERROR/BYE 负载使用 scope=binary 的
子集（bad_frame、bad_crc、payload_cap_too_small、bad_hello、epoch_mismatch、bad_token、
internal_error）；scope=both 表示两处通用。错误码只增不改语义；新增错误码必须更新版本兼容说明。

## 9. 版本与兼容
- 主版本（version）不同即不兼容：拒绝并关闭。
- 次版本通过可选字段/未知 op 扩展；接收方忽略未知字段，未知 op 返回 unknown_op。
- 冻结字段/枚举编号/单位不得单方面改变；变更需升版本并在 UI_BACKEND_HANDOFF.md 说明。

## 10. 模拟与真实性
- 确定性测试服务器：apps/sixmic-desktop/backend/sixmic_backend/testing/mock_ps_server.py，
  所有数据带 sourceKind:"test-fixture"，schema 内含 simulated:true。
- PC 后端测试可用 fixture，但产品运行时不得自动回退到演示数据：Live 模式下无数据即
  显示无数据/no_link，不得用 fixture 顶替。
- 未实机联调前，文档只能写"协议与夹具测试通过，实板未联调"。
