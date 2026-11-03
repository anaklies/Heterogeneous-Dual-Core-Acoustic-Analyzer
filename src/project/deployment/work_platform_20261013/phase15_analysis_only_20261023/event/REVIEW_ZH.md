# 审查与验证记录

2026-10-23，本目录独立实现统计量事件核。

主任务 GPT 对 RTL 独立审查后提出：阻塞旧 summary 时提交新配置需携带配置代号；配置修改取消活动必须明确区别正常结束；时间重启、频带功率单位、功率下降与节律缺失的区别必须写入契约。均采纳：新增实时及逐结果锁存的 32 位配置代号，拒绝代号回绕，加入阻塞期间提交的定向测试，更新中文接口说明。主任务复核了乘法比较扩展位宽。

一次有限 DeepSeek API 工作者独立审查未完成，没有可用审查文字。`deepseek_review_result.json` 保留返回模型、状态、请求 ID、token 用量与任务 SHA；输入任务保留在 `deepseek_review_task.txt`。状态 incomplete，输出预算 3000 tokens 全部为 reasoning，实际 text 为空。不重试、不当成审查通过，也不把 API 工作者称为原生子代理。该任务是在加入配置代号前提交，不能作为最终代码的验收。

最终实际运行 Vivado 2025.2 xvlog/xelab/xsim：`PASS event_power_detector checks=36 starts=3 sticky_fault=0f`。最终 `xsim.log` 保留证据。未执行综合、布局布线或实板运行。定向测试不证明旧 Python 算法逐位一致、全天误报率或完整事件存储服务。
