"""Workflow definitions for the echo-features-1 fixed-hidden launch flows.

This module is intentionally pure data + tiny pure functions: it maps a feature
spec entry to the documented workflow steps, the only user actions and the only
required confirmations.  It never builds parameter editors: every measurement
parameter comes from ``feature.launch`` (policy=fixed-hidden) and only the
documented flow values (stimulus, referenceJobId, confirmed, testSignalConfirmed,
referenceConfirmed) are injected by the runtime.
"""
from __future__ import annotations

from typing import Any

STEP_LABELS = {
    "run": ("启动测量", "Run measurement"),
    "reference": ("建立参考", "Capture reference"),
    "confirm": ("确认测量链", "Confirm chain"),
    "stimulus": ("选择激励", "Select stimulus"),
    "compare": ("比较", "Compare"),
    "measure": ("测量", "Measure"),
    "monitor": ("持续监测", "Continuous monitoring"),
}

ACTION_LABELS = {
    "run": ("运行", "Run"),
    "stop": ("停止", "Stop"),
    "refresh": ("刷新", "Refresh"),
    "reference": ("建立参考", "Capture reference"),
    "compare": ("比较", "Compare"),
    "measure": ("测量", "Measure"),
    "save": ("保存图像", "Save image"),
    "export": ("导出原始数据", "Export raw"),
}

ACTION_ICONS = {
    "run": "play", "stop": "square", "refresh": "refresh-cw",
    "reference": "target", "compare": "git-compare", "measure": "play",
    "save": "save", "export": "download",
}

ACTION_TONES = {
    "run": "primary", "stop": "danger", "refresh": "secondary",
    "reference": "primary", "compare": "primary", "measure": "primary",
    "save": "ghost", "export": "ghost",
}

CONFIRMATION_LABELS = {
    "stimulus": ("房间激励方式（拍手 / 脉冲）", "Room stimulus (clap / impulse)"),
    "chain-confirm": ("同激励 / 增益 / 测量链已保持",
                      "Same excitation / gain / measurement chain"),
    "testSignalConfirmed": ("测试信号已确认", "Test signal confirmed"),
    "referenceConfirmed": ("名义数字参考已声明（非声学校准）",
                           "Nominal digital reference declared (not acoustic calibration)"),
}

OPTION_LABELS = {
    "clap": ("拍手", "Clap"),
    "impulse": ("脉冲", "Impulse"),
}

VARIANT_LABELS = {
    "A": ("A频率计权", "A frequency weighting"),
    "C": ("C频率计权", "C frequency weighting"),
    "Z": ("Z频率计权", "Z frequency weighting"),
    "frequency": ("A/C/Z 相对频率计权", "A/C/Z relative frequency weighting"),
    "time": ("Z 未计权 FAST/SLOW/LeqFS", "Z unweighted FAST/SLOW/LeqFS"),
    "NR": ("NR 曲线估计", "NR curve estimate"),
    "NC": ("NC 曲线估计", "NC curve estimate"),
}

FLOW_NOTES = {
    "reference_compare": "先建立并保存参考，再在同一通道/网格/增益/来源上比较；"
                         "阈值标志是绝对变化标志，不是 dB SPL 限值。",
    "reference_measure": "参考与测量必须保持同激励/增益/测量链；结果是相对差异，"
                         "不得标注为 Rw。",
    "staged_stipa": "实验性 STIPA：先取得已知测试参考（PCM 长采集），确认测试信号后"
                    "再执行 101 阶段；全部 valid 才显示实验指数，不是认证 STIPA。",
    "room_stimulus": "需显式选择房间激励（拍手/脉冲）后才启动；PL 做近似起始截取，"
                     "普通语音不得自动当作 RIR，不是认证 RT60。",
    "dual_variant": "两次独立运行，结果分开标注，严禁合并为单一计权/曲线。",
    "monitor": "持续监测：不轮询未完成监测任务的 feature.result；停止后等待 canceled，"
               "事件经 event 链与 48121 获取。",
    "single": "",
}


def _pair(label: tuple[str, str], zh: str | None = None, en: str | None = None) -> dict[str, str]:
    return {"zh": zh or label[0], "en": en or label[1]}


def _step(step_id: str) -> dict[str, str]:
    label = STEP_LABELS.get(step_id, (step_id, step_id))
    return {"id": step_id, "labelZh": label[0], "labelEn": label[1]}


def _action(action_id: str) -> dict[str, Any]:
    label = ACTION_LABELS.get(action_id, (action_id, action_id))
    return {"id": action_id, "labelZh": label[0], "labelEn": label[1],
            "icon": ACTION_ICONS.get(action_id, "activity"),
            "tone": ACTION_TONES.get(action_id, "secondary"),
            "enabled": True, "reason": {"zh": "", "en": ""}}


def _confirmation(confirmation_id: str, kind: str = "bool", *,
                  options: list[str] | None = None,
                  value: Any = None, required: bool = True) -> dict[str, Any]:
    label = CONFIRMATION_LABELS.get(confirmation_id, (confirmation_id, confirmation_id))
    item: dict[str, Any] = {
        "id": confirmation_id,
        "type": kind,
        "labelZh": label[0],
        "labelEn": label[1],
        "value": value,
        "required": bool(required),
        "enabled": True,
        "reason": {"zh": "", "en": ""},
    }
    if kind == "enum":
        item["options"] = [
            {"value": option,
             "labelZh": OPTION_LABELS.get(option, (option, option))[0],
             "labelEn": OPTION_LABELS.get(option, (option, option))[1]}
            for option in (options or ["clap", "impulse"])
        ]
    return item


def flow_kind(feature: dict[str, Any]) -> str:
    launch = feature.get("launch") if isinstance(feature.get("launch"), dict) else {}
    kind = str(launch.get("kind") or "single")
    if kind in FLOW_NOTES:
        return kind
    mode = str(feature.get("mode") or "")
    if mode == "events" or kind == "monitor":
        return "monitor"
    return "single"


def flow_definition(feature: dict[str, Any]) -> dict[str, Any]:
    """Static flow: ordered steps, standard actions and required confirmations."""
    launch = feature.get("launch") if isinstance(feature.get("launch"), dict) else {}
    special = feature.get("specialFlow") if isinstance(feature.get("specialFlow"), dict) else {}
    kind = flow_kind(feature)
    steps: list[str]
    actions: list[str] = ["run", "stop", "refresh", "save", "export"]
    confirmations: list[dict[str, Any]] = []
    if kind == "reference_compare":
        steps = ["reference", "compare"]
        actions = ["reference", "compare", "stop", "refresh", "save", "export"]
    elif kind == "reference_measure":
        steps = ["reference", "confirm", "measure"]
        actions = ["reference", "measure", "stop", "refresh", "save", "export"]
        confirmations = [_confirmation("chain-confirm")]
    elif kind == "staged_stipa":
        steps = ["reference", "confirm", "measure"]
        actions = ["reference", "measure", "stop", "refresh", "save", "export"]
        confirmations = [_confirmation("testSignalConfirmed")]
    elif kind == "room_stimulus":
        steps = ["stimulus", "measure"]
        actions = ["run", "stop", "refresh", "save", "export"]
        confirmations = [_confirmation("stimulus", "enum",
                                       options=list(special.get("stimulusEnum")
                                                    or ["clap", "impulse"]))]
    elif kind == "dual_variant":
        steps = ["run"]
        confirmations = []
        if str(special.get("type") or "") == "noise_rating":
            confirmations = [_confirmation("referenceConfirmed")]
        elif launch.get("confirmation") == "referenceConfirmed":
            confirmations = [_confirmation("referenceConfirmed")]
    elif kind == "monitor":
        steps = ["monitor"]
        actions = ["run", "stop", "refresh", "save", "export"]
    else:
        steps = ["run"]
    return {
        "kind": kind,
        "steps": [_step(step_id) for step_id in steps],
        "stepIds": steps,
        "actions": [_action(action_id) for action_id in actions],
        "confirmations": confirmations,
        "note": FLOW_NOTES.get(kind, ""),
    }


def run_plan(feature: dict[str, Any]) -> list[dict[str, Any]]:
    """Fixed-hidden run sequence for one feature (params come from the spec only).

    Each entry describes one device job: role, fixed params, variant id (for
    dual-variant results) and the documented values that must be injected later
    (referenceJobId / confirmed / stimulus).
    """
    launch = feature.get("launch") if isinstance(feature.get("launch"), dict) else {}
    special = feature.get("specialFlow") if isinstance(feature.get("specialFlow"), dict) else {}
    kind = flow_kind(feature)
    base_params = dict(launch.get("params") or {})
    if launch.get("runs") and kind == "dual_variant":
        plan = []
        for run in launch.get("runs") or []:
            run = run if isinstance(run, dict) else {}
            variant_id = str(run.get("id") or "")
            params = dict(base_params)
            params.update(run.get("params") or {})
            plan.append({"role": "variant", "variantId": variant_id,
                         "params": params, "inject": []})
        return plan
    if kind == "reference_compare":
        reference_params = dict(launch.get("referenceParams") or {})
        reference_params.setdefault("action", str(special.get("referenceAction") or "reference"))
        compare_params = dict(launch.get("compareParams") or {})
        compare_params.setdefault("action", str(special.get("compareAction") or "compare"))
        reference_params.update(base_params)
        compare_params.update(base_params)
        return [
            {"role": "reference", "variantId": "", "params": reference_params,
             "inject": []},
            {"role": "primary", "variantId": "",
             "params": compare_params,
             "inject": [str(special.get("referenceParam") or "referenceJobId")]},
        ]
    if kind == "reference_measure":
        reference_params = dict(launch.get("referenceParams") or {})
        reference_params.setdefault("action", str(special.get("referenceAction")
                                                  or "reference"))
        measure_params = dict(launch.get("measureParams") or {})
        measure_params.setdefault("action", str(special.get("measureAction") or "measure"))
        reference_params.update(base_params)
        measure_params.update(base_params)
        inject = [str(special.get("referenceParam") or "referenceJobId")]
        confirm_param = str(special.get("confirmParam") or "confirmed")
        inject.append(confirm_param)
        return [
            {"role": "reference", "variantId": "", "params": reference_params,
             "inject": []},
            {"role": "primary", "variantId": "", "params": measure_params,
             "inject": inject, "confirmParam": confirm_param},
        ]
    if kind == "staged_stipa":
        reference_params = dict(launch.get("referenceParams") or {})
        reference_params.update(base_params)
        stipa_params = dict(launch.get("stipaParams") or {})
        stipa_params.update(base_params)
        return [
            {"role": "reference", "variantId": "",
             "params": reference_params,
             "referenceFeature": str(special.get("referenceFeature") or "io_pcm"),
             "inject": []},
            {"role": "primary", "variantId": "", "params": stipa_params,
             "inject": ["referenceJobId", "testSignalConfirmed"]},
        ]
    if kind == "room_stimulus":
        params = dict(base_params)
        return [{"role": "primary", "variantId": "", "params": params,
                 "inject": [str(special.get("stimulusParam") or "stimulus")]}]
    if str(feature.get("featureId") or "") == "relative_insulation":
        params = dict(base_params)
        return [{"role": "primary", "variantId": "", "params": params, "inject": []}]
    return [{"role": "primary", "variantId": "", "params": base_params, "inject": []}]


def variant_definition(feature: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """UI variant descriptor for one dual-variant run."""
    variant_id = str(run.get("variantId") or "")
    label = VARIANT_LABELS.get(variant_id, None)
    return {
        "id": variant_id,
        "labelZh": label[0] if label else variant_id,
        "labelEn": label[1] if label else variant_id,
        "state": "idle",
        "chart": None,
    }


def confirmation_defaults(feature: dict[str, Any]) -> dict[str, Any]:
    """Initial confirmation values (room stimulus starts unselected)."""
    values: dict[str, Any] = {}
    for item in flow_definition(feature)["confirmations"]:
        if item["type"] == "enum":
            values[item["id"]] = None
        else:
            values[item["id"]] = False
    return values
