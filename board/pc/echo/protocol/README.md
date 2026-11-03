# pc_backend_v1 接口冻结包（sixmic-analysis v1 + DTO + 功能目录）

状态：**FROZEN-1 / 2026-10-24**。本目录是 PC 后端、PS 网关与主 Agent 前端之间的契约来源。
任何字段/单位/枚举编号变更都必须升版本并在
`C:/Users/sunxi/Desktop/sixmic3D/apps/sixmic-desktop/docs/backend/UI_BACKEND_HANDOFF.md`
显式说明，禁止单方面静默改变。

| 路径 | 内容 |
|---|---|
| PROTOCOL.md | 新网络协议 sixmic-analysis v1（控制 48120 JSON-Lines / 二进制 48121 SMA1） |
| device/MMIO_PROTOCOL3.md | 板级 MMIO 协议 3 寄存器/结果字/clip/服务发布头（读自真实 RTL） |
| c/sixmic_analysis_wire.h | 两端共享 C99 常量与编解码辅助（显式小端，含 CRC32） |
| schema/control.schema.json | 控制通道请求/响应/事件 envelope |
| schema/dto.schema.json | PC 后端 DTO（64 位计数为十进制字符串） |
| schema/status.schema.json | status.get 快照 |
| schema/stream-schema.schema.json | 二进制 STREAM_SCHEMA 负载 |
| dto/DTO.md | DTO 字段语义、有效性、null-vs-0、buffer 生命周期 |
| errors/ERROR_CATALOG.json | 稳定错误码/messageKey/可重试性 |
| features/FEATURE_CATALOG.json/.md | 52 行功能目录，逐行继承真实 CSV；状态=证据推导 |
| golden/ | 冻结 wire 样例（20 个文件，含 sha256 清单）；PC/PS 双方逐字节对照 |
| tools/generate_golden.py | 确定性生成器（stdlib，接口冻结后不得随意重生成） |
| tools/generate_feature_catalog.py | 从真实 FUNCTION_EXECUTION_MAP.csv 生成功能目录 |

## 冻结规则

1. **真实优先**：`PROTOCOL.md` 描述的是本轮新实现，不是旧 48110 服务；旧服务保持独立。
2. **版本分离**：网络协议版本 1 与板级 MMIO 协议 3 是两套号，不得混用。
3. **golden 是 oracle**：编解码器必须能复现 `golden/GOLDEN_MANIFEST.json` 的字节与 sha256；
   参考实现见 `apps/sixmic-desktop/tests/backend/test_protocol_framing.py` 与
   `deployment/ps_analysis_gateway/` 的 host 测试。
4. **64 位整数**：JSON 中为十进制字符串；Python 内部 int；QML 不得做 double 运算。
5. **真实性标记**：`sourceKind` 只允许 pl-live / file-replay / offline-reference /
   test-fixture；fixture 不得标 pl-live。
6. **能力状态**：available 需要真实后端/固件与验收证据；当前功能目录 available=0。
7. **golden 重生成**只允许在接口版本变更时进行，并需同步两侧测试与 handoff 记录。

## 生成与校验命令

```powershell
python C:/Users/sunxi/Desktop/sixmic3D/interfaces/pc_backend_v1/tools/generate_golden.py
python C:/Users/sunxi/Desktop/sixmic3D/interfaces/pc_backend_v1/tools/generate_feature_catalog.py
cd C:/Users/sunxi/Desktop/sixmic3D/apps/sixmic-desktop/backend
python -m sixmic_backend.app.backend_check --self-test --protocol-dir C:/Users/sunxi/Desktop/sixmic3D/interfaces/pc_backend_v1
```
