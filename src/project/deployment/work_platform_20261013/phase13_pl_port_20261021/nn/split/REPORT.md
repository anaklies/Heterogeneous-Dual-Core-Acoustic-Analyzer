# 单次低成本ROM结构修复

本副本仅把30958-word整体权重表拆为state tensor独立`W_*`常量数组，消除每个outlined loop看到完整权重地址空间的结构诱因。
没有改变卷积、GELU、GRU、输出计算、权重、数据类型或运算次序。原nn源码和原HLS失败证据保持不变。

新入口：`split/srpdnn_float.cpp`、`split/srpdnn_float.h`、`split/weights_float.h`。
复现：`build_split.py`生成副本与头、原编译参数编译并比较。

相同实际M speech特征、完整15麦对76576输出：新旧native C++输出逐bit一致，与既有Torch黄金亦通过原atol/rtol=2e-4。
源码/输入/输出哈希及各ROM参数见`SPLIT_COMPARISON.json`。

本子任务没有执行HLS，不能宣称BRAM已经降低到器件预算，也没有关闭周期超限。仍需主智能体用相同HLS探针测量实际BRAM/DSP与延迟。
