#ifndef SIXMIC_FAULT_CATALOG_H
#define SIXMIC_FAULT_CATALOG_H
#include <QtCore>
#include "../sixmic_faults.h"
struct FaultDescription
{
    QString title, location, cause, action, impact;
    bool blocking = false;
    QString html() const
    {
        return "<h3>" + title.toHtmlEscaped() + "</h3><p>" + location.toHtmlEscaped() + "<br>" +
               cause.toHtmlEscaped() + "<br>" + impact.toHtmlEscaped() + "<br><b>" +
               action.toHtmlEscaped() + "</b></p>";
    }
};
inline FaultDescription activeFaultDescription(int bit, bool en)
{
    FaultDescription f;
    f.blocking = !!((1u << bit) & SIXMIC_BLOCKING_FAULTS);
    f.impact = en ? (f.blocking ? "Impact: live coordinates are hidden."
                                : "Impact: warning/fallback; localization may continue.")
                  : (f.blocking ? "影响：停止显示本轮实时坐标。"
                                : "影响：警告或降级，符合条件时仍可定位。");
    if (bit < 6)
    {
        f.title = (en ? QString("MIC%1 data stalled") : QString("麦克风 %1 数据停滞")).arg(bit + 1);
        f.location = en ? "Location: microphone PCM capture" : "位置：麦克风数据采集通道";
        f.cause =
            en ? "Possible causes: loose data wire, missing power, stalled capture; silence may "
                 "resemble this."
               : "可能原因：数据线松动、供电异常或采集停滞；静音也可能触发，不能仅凭此判定断线。";
        f.action = en ? "Check this channel's power, ground and SD wire, then play a test sound."
                      : "处理：检查该路电源、地和 SD 数据线，再播放声音观察是否恢复。";
        return f;
    }
    if (bit < 12)
    {
        f.title = (en ? QString("MIC%1 clipping") : QString("麦克风 %1 削顶")).arg(bit - 5);
        f.location = en ? "Location: microphone signal amplitude" : "位置：麦克风输入幅度";
        f.cause = en ? "Possible causes: excessive sound level or repeated full-scale samples."
                     : "可能原因：声音过大或数据持续达到满量程。";
        f.action = en ? "Lower speaker volume; if it persists in quiet, inspect wiring/capture."
                      : "处理：降低播放音量；安静时仍出现则检查接线和采集格式。";
        return f;
    }
    if (bit < 17)
    {
        f.title = (en ? QString("MIC%1 repeats MIC1 data") : QString("麦克风 %1 与 1 数据重复"))
                      .arg(bit - 10);
        f.location = en ? "Location: channel independence" : "位置：六路数据独立性";
        f.cause = en ? "Possible shared SD wire, or genuinely coherent/silent signals; this is "
                       "diagnostic evidence."
                     : "可能原因：数据线共接，也可能是相干声音或静音；这只是疑似异常证据。";
        f.action = en ? "Check separate SD wires and compare channels with a nearby test sound."
                      : "处理：检查各路 SD 独立连接，用近距离声音比较通道变化。";
        return f;
    }
    const char *titles[] = {
        "采样中断",       "IMU 姿态不可用", "温度不可用",         "传感器事务/温度范围异常",
        "SHT30 通信失败", "SHT30 校验失败", "IMU 姿态数据不合法", "频谱窗口积压",
        "窗口输入削顶",   "FFT 协议错误",   "特征/CNN/配置异常",  "定位或跟踪处理异常",
        "PL 处理超时",    "结果输出超时",   "PL 自动恢复次数耗尽"};
    const char *locations[] = {
        "音频采样与时钟", "IMU 读取/姿态有效性", "SHT30 温度补偿",          "传感器状态汇总",
        "SHT30 I²C 事务", "SHT30 CRC 校验",      "IMU 四元数校验",          "STFT 窗口缓存",
        "STFT 输入窗口",  "FFT 输入输出握手",    "特征提取、CNN或配置装载", "定位、跟踪及结果发布",
        "PL 调度/计算链", "结果发布与接收握手",  "PL 局部恢复控制"};
    const char *causes[] = {"有效采样超过100ms未到达。",
                            "姿态尚未有效、已过期或读取失败。",
                            "温度尚未有效或已过期，将使用19.3°C默认值。",
                            "IMU通信失败或温度超出补偿范围，须结合传感器详情。",
                            "地址、供电、连线或总线响应异常。",
                            "收到的数据校验不一致，不代表传感器一定损坏。",
                            "四元数范数或数据格式不符合要求。",
                            "处理未及时消费输入，窗口被覆盖或积压。",
                            "输入发生饱和，波形可能失真。",
                            "帧边界或握手顺序不符合FFT接口约定。",
                            "特征、权重或配置加载/执行未完成或报错。",
                            "后端报告故障；当前PL接口未提供内部编号时只能定位到此阶段。",
                            "计算持续忙且超过保护上限。",
                            "下游未按时接收完整结果。",
                            "连续局部恢复达到3次，已停止自动尝试。"};
    const char *actions[] = {"检查BCLK/WS、六路SD和采集模块。",
                             "检查IMU电源、I²C接线和安装；恢复前使用本地坐标提示。",
                             "检查SHT30接线及供电，不把默认值当实测温度。",
                             "查看下方传感器明细，检查温度范围和I²C。",
                             "检查SHT30的3.3V、地、SDA/SCL和0x44/0x45地址。",
                             "检查I²C线长、上拉和接触，等待新的有效温度。",
                             "检查IMU通信及传感器状态，不使用损坏姿态。",
                             "观察是否自动恢复；反复出现需检查处理时序与负载。",
                             "先降低声音电平；持续异常需检查采样/定点格式。",
                             "检查FFT帧长度、TLAST及背压连接。",
                             "检查相关模块和配置；不能仅凭此确定CNN算法精度故障。",
                             "查看固件内部故障码或日志；勿猜测具体子模块原因。",
                             "检查计算链是否停滞及实际处理耗时。",
                             "检查PS接收进程、AXI和结果握手。",
                             "先修复根因，再显式重新初始化PL；PS重连不能代替PL复位。"};
    const char *et[] = {"Sampling stopped",
                        "IMU unavailable",
                        "Temperature unavailable",
                        "Sensor transaction/range fault",
                        "SHT30 communication failed",
                        "SHT30 CRC failed",
                        "IMU quaternion invalid",
                        "STFT overrun",
                        "Window clipping",
                        "FFT protocol error",
                        "Features/CNN/config fault",
                        "Localization/tracker fault",
                        "PL computation timeout",
                        "Result output timeout",
                        "PL recovery exhausted"};
    const char *ea[] = {"Check BCLK/WS, SD wires and capture.",
                        "Inspect IMU power/I2C; array-local fallback applies.",
                        "Inspect SHT30; default 19.3 C is not measured temperature.",
                        "Inspect sensor detail bits and compensation range.",
                        "Inspect power, SDA/SCL, pullups and sensor address.",
                        "Inspect I2C integrity and wait for valid data.",
                        "Inspect IMU data and sensor state.",
                        "Inspect processing load/window timing if recovery repeats.",
                        "Reduce level, then inspect sample format.",
                        "Inspect FFT length, TLAST and backpressure.",
                        "Inspect features, weights/config and execution.",
                        "Inspect internal firmware/logs; subtype may not be exported.",
                        "Inspect stalled stages and actual compute duration.",
                        "Inspect PS collector, AXI and output handshake.",
                        "Fix the cause and reinitialize PL; PS reconnect is not PL reset."};
    int i = bit - 17;
    f.title = QString::fromUtf8(en ? et[i] : titles[i]);
    f.location = en ? "Location: " + QString::fromUtf8(et[i])
                    : QString::fromUtf8("位置：") + QString::fromUtf8(locations[i]);
    f.cause = en ? "Meaning: " + f.title
                 : QString::fromUtf8("可能原因/触发条件：") + QString::fromUtf8(causes[i]);
    f.action = QString::fromUtf8(en ? ea[i] : actions[i]);
    return f;
}
inline FaultDescription receiverFaultDescription(int code, bool en)
{
    const char *zh[] = {"接收器参数不完整",   "PL/PS 接口版本不匹配",   "结果过期或计时复位",
                        "定位帧执行失败",     "声源数量越界",           "目标字段格式不合法",
                        "同一帧出现重复编号", "方向向量异常",           "坐标与距离不一致",
                        "AXI/寄存器读取失败", "读取中发生复位或帧变化", "PL 周期计数读取不稳定",
                        "结果确认 ACK 失败"};
    const char *et[] = {"Receiver configuration missing",
                        "PL/PS ABI mismatch",
                        "Stale frame or counter reset",
                        "Localization frame failed",
                        "Source count invalid",
                        "Invalid target fields",
                        "Duplicate IDs",
                        "Invalid direction",
                        "XYZ/range mismatch",
                        "AXI/register read failed",
                        "Frame changed during read",
                        "Unstable PL counter read",
                        "Frame ACK failed"};
    FaultDescription f;
    f.blocking = true;
    int i = -code - 1;
    if (i < 0 || i >= 13)
        f.title = en ? "Unknown receiver report" : "未识别的接收报告";
    else
        f.title = QString::fromUtf8(en ? et[i] : zh[i]);
    f.location = en ? "Location: PS frame receiver/validation" : "位置：PS 数据接收与完整帧校验";
    f.cause = en ? "This report rejects the affected coordinates; it does not identify a specific "
                   "disconnected wire."
                 : "此报告表示该坐标帧不能被可信接收，不足以直接判断某根线断开。";
    f.action =
        en ? "Check matching firmware, collector logs, AXI/clock and the next complete frame."
           : "处理：检查固件版本一致性、接收日志、AXI/时钟，并等待下一完整有效帧。";
    f.impact = en ? "Impact: affected live coordinates hidden." : "影响：不显示该帧实时坐标。";
    return f;
}
inline FaultDescription backendFaultDescription(int code, bool en)
{
    const char *zh[] = {
        "定位输出写入越界/冲突", "定位结果帧不完整",      "定位计算超时", "跟踪输出写入越界/冲突",
        "跟踪结果帧不完整",      "跟踪计算超时",          "声源数越界",   "控制状态异常",
        "结果接收超时",          "采集窗口失效，本轮中止"};
    const char *et[] = {"MUSIC output address conflict",
                        "MUSIC frame incomplete",
                        "MUSIC timeout",
                        "Tracker output address conflict",
                        "Tracker frame incomplete",
                        "Tracker timeout",
                        "Source count overflow",
                        "Control state invalid",
                        "Result receive timeout",
                        "Acquisition invalid; window aborted"};
    FaultDescription f;
    f.blocking = true;
    f.title = code >= 1 && code <= 10 ? QString::fromUtf8(en ? et[code - 1] : zh[code - 1])
                                      : (en ? "Unknown backend report" : "未识别的内部报告");
    f.location =
        en ? "Location: PL localization/tracking sequencer" : "位置：PL 定位/跟踪结果控制器";
    f.cause = en ? "Defined internal control fault; not a measured acoustic error."
                 : "固件定义的内部控制故障，不是声学定位误差指标。";
    f.action = en ? "Inspect this stage's output addresses, completeness, handshake and timeout; "
                    "then reinitialize safely."
                  : "处理：检查对应阶段的输出地址、完整性、握手和超时，再修复并重新初始化。";
    f.impact = en ? "Impact: incomplete/failed frame hidden." : "影响：丢弃失败帧。";
    return f;
}
inline QList<FaultDescription> knownFaults(uint32_t bits, uint8_t sensors, bool en)
{
    QList<FaultDescription> out;
    for (int i = 0; i < 32; ++i)
        if (bits & (1u << i))
            out << activeFaultDescription(i, en);
    const int mapped[] = {20, 21, 22, 23, 20, 20};
    for (int i = 0; i < 6; ++i)
        if (sensors & (1u << i))
        {
            auto f = activeFaultDescription(mapped[i], en);
            if (i == 4)
            {
                f.title = en ? "Temperature outside supported range" : "温度超出补偿范围";
                f.cause =
                    en ? "Valid compensation range: -20 to 60 C." : "当前补偿范围为−20～60°C。";
            }
            if (i == 5)
            {
                f.title = en ? "IMU pressure unavailable" : "IMU 气压不可用";
                f.location = en ? "Location: IMU registers 0x45/0x46" : "位置：IMU 气压寄存器 0x45/0x46";
                f.cause = en ? "Pressure read failed or value is outside 30..120 kPa." : "气压读取失败或读数不在30～120kPa范围。";
                f.action = en ? "Check IMU pressure capability and I2C; standard-pressure compensation remains available." : "处理：检查IMU气压功能和I²C；系统继续采用标准气压补偿。";
                f.blocking = false;
            }
            out << f;
        }
    if (sensors & 0xc0)
    {
        FaultDescription f;
        f.title = en ? "Unknown sensor status bits" : "传感器保留状态位非零";
        f.location = en ? "Location: sensor ABI" : "位置：传感器接口版本";
        f.cause = en ? "These bits are not defined by current firmware."
                     : "当前固件未定义这些位，不猜测具体设备故障。";
        f.action = en ? "Check matching firmware." : "处理：检查固件版本。";
        out << f;
    }
    return out;
}
struct DemoFaultScenario
{
    QString name;
    uint32_t bits = 0;
    uint8_t sensors = 0;
    int receiver = 0, backend = 0;
    bool disconnected = false, empty = false;
};
inline QList<DemoFaultScenario> faultScenarios(bool en)
{
    QList<DemoFaultScenario> list;
    DemoFaultScenario normal;
    normal.name = en ? "Normal" : "正常";
    list << normal;
    DemoFaultScenario empty;
    empty.name = en ? "No sound (normal)" : "没有声源（正常，不报故障）";
    empty.empty = true;
    list << empty;
    DemoFaultScenario off;
    off.name = en ? "Result link disconnected" : "结果连接中断";
    off.disconnected = true;
    list << off;
    for (int i = 0; i < 32; ++i)
    {
        DemoFaultScenario s;
        s.name = activeFaultDescription(i, en).title;
        s.bits = 1u << i;
        list << s;
    }
    for (int i = 0; i < 6; ++i)
    {
        DemoFaultScenario s;
        s.sensors = 1u << i;
        s.name = knownFaults(0, s.sensors, en).first().title;
        list << s;
    }
    for (int i = 1; i <= 10; ++i)
    {
        DemoFaultScenario s;
        s.backend = i;
        s.bits = 1u << 28;
        s.name = backendFaultDescription(i, en).title;
        list << s;
    }
    for (int i = 1; i <= 13; ++i)
    {
        DemoFaultScenario s;
        s.receiver = -i;
        s.name = receiverFaultDescription(-i, en).title;
        list << s;
    }
    return list;
}
#endif
