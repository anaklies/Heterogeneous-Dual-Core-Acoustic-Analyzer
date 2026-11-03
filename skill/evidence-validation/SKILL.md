---
name: evidence-validation
description: 用标准库工具检查黄金结果差异和工程哈希，并明确软件、RTL、板测证据边界。
---

## 使用
Python3.10+，不依赖板卡、EDA或第三方库。
`python scripts/verify.py compare --actual actual.json --reference reference.json --atol 0 --rtol 0`
输入为JSON数值数组（可嵌套），按形状与元素比较；浮点容差为abs(a-r)<=atol+rtol*abs(r)，拒绝NaN/Inf，整数精确比较。位级对照用hex模式：
`python scripts/verify.py compare --actual actual.txt --reference reference.txt --format hex`
每个空白分隔token为一个32位十六进制字，可带0x；不允许用浮点容差代替位一致。
`python scripts/verify.py manifest --root PROJECT --manifest FILES_SHA256.json`
清单格式为[{"path":"relative/file","sha256":"64hex"}]，拒绝重复、绝对及越界路径。只读，不自动修复错误。

## 来源及已验证效果
ECHO整理过程中曾只有结果说明而缺少输入与逐项参考；因此必须核对实际路径和内容，不能只数文件。项目保留45项输入/参考和92个原生用例。本技能新增工具以匹配、数值不匹配、长度/结构不匹配、整数精度、非法值、位一致及路径越界等小夹具验证，结果见tests/RESULT.json。

## 边界
容差必须在查看DUT结果前依据数值格式确定；不能为通过测试扩大容差。哈希只能证明文件一致，不能证明算法正确；软件模型通过不能替代RTL/板测。工具不对寄存器或设备执行任何读写。
