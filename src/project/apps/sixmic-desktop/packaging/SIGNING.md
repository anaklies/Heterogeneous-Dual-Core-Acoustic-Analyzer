# Windows Authenticode 签名说明（SixMic3D）

更新：2026-10-25。当前发布物 **未签名（NotSigned）**，原因与可执行方案如下。

## 1. 为什么当前无法让所有 Windows 电脑都信任

Authenticode 的可信链来自公众信任的 CA 代码签名证书：

1. 需要 OV 或 EV 代码签名证书；
2. CA 要核验申请者身份（个人/学校/公司资料等），通常 1–10 个工作日；
3. 证书私钥必须由申请者保管（PFX/硬件令牌/HSM），不能由第三方代生成；
4. 本机无任何代码签名证书、无 signtool/Windows SDK、无私钥材料，因此不能凭空生成被全网信任的签名；
   自签名证书只有在目标电脑手动安装其根证书后才被信任，不能作为公开分发信任。

可选来源（自行申请）：
- DigiCert / Sectigo / GlobalSign 等 OV 代码签名（常见约 100–300 美元/年）；
- EV 代码签名（约 300–500 美元/年，通常需硬件令牌/云 HSM；对 SmartScreen 声誉更有利）；
- Certum Open Source Code Signing（符合其开源项目条件时免费/低价）；
- SignPath.io 等面向开源项目的托管签名服务（需项目许可证与账号审核）。
任何途径都需真实身份审核，无法在无证书的构建机上完成。

## 2. 证书到位后的签名流程（已实现脚本）

脚本：apps/sixmic-desktop/packaging/sign_artifacts.ps1

PFX 方式（推荐，私钥不入库）：
    powershell -NoProfile -ExecutionPolicy Bypass -File packaging/sign_artifacts.ps1 -PfxPath C:/secure/codesign.pfx

或使用本机证书存储中的指纹：
    powershell -NoProfile -ExecutionPolicy Bypass -File packaging/sign_artifacts.ps1 -Thumbprint THUMBPRINT -TimestampUrl http://timestamp.digicert.com

脚本行为：
- 支持 signtool.exe（Windows SDK）或 PowerShell Set-AuthenticodeSignature；
- 强制检查私钥、Code Signing EKU、有效期；自签名必须显式 -AllowSelfSignedTest；
- SHA-256 摘要 + RFC3161 时间戳（可用 -SkipTimestamp 关闭）；
- 逐文件复制到 dist/authenticode/ 后签名，不覆盖原始构建；
- 输出 signing-evidence.json：大小、sha256、签名状态、签名者主题/指纹、时间戳者、是否本机受信；
- 任一步失败返回非 0，避免假签名。

推荐签名顺序（保证安装包内也是已签名 exe）：
1. 签名 SixMic3D.exe（及 SixMic3D-BackendCheck.exe）；
2. 用已签名 exe 重新生成安装包；
3. 签名 SixMic3D-Setup-x64.exe；
4. 重新生成便携 ZIP（ZIP 本身无 Authenticode，分发页给出 SHA256）；
5. 重新计算并发布 SHA256；更新 ACCEPTANCE_REPORT.md 与安装证据。

## 3. 自签名演示（仅内部测试，不代表可分发）

- 测试证书公钥：packaging/signing-test/SixMic3D-TestSigning.cer（CN=SixMic3D Test Signing，NOT FOR DISTRIBUTION）；
  私钥仅存在于本机构建用户的证书存储中，未导出。
- 已用脚本对构建副本签名，证据：dist/authenticode-test/signing-evidence.json；
  Get-AuthenticodeSignature 状态为 UnknownError（根证书不受信），trustedOnThisMachine=false。
- 若需在内部测试机验证签名有效，可把该 .cer 导入受信任的根证书颁发机构，仅限测试机；禁止随产品分发该证书或宣称公开可信。

## 4. SmartScreen 与分发建议

- 新证书也需要声誉积累；EV 证书通常更快获得 SmartScreen 信任；
- 每次发布用同一证书签名，并保留 RFC3161 时间戳；
- 同时发布 SHA256 与签名者信息，便于用户校验；
- 在证书未到位前，只能如实标注未签名，不能声称可在所有 Windows 电脑上被信任。
