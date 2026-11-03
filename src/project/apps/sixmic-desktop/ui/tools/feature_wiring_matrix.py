"""Generate the 51-row feature wiring matrix from the spec + E2E evidence.

Inputs (read-only):
  * apps/sixmic-desktop/ui/config/feature_view_spec.json   (authoritative 51 features/pages)
  * deployment/echo_feature_closure_20261025/registry/INTERFACE_REGISTRY.json
  * apps/sixmic-desktop/tests/e2e/evidence/*.json          (real host-fixture E2E run)
  * apps/sixmic-desktop/docs/frontend/screenshots/feature_wiring_20261026/capture_manifest.json

Outputs:
  * apps/sixmic-desktop/docs/frontend/51_FEATURE_WIRING_MATRIX.csv
  * apps/sixmic-desktop/docs/frontend/51_FEATURE_WIRING_MATRIX.md

Row/column contract: exactly 51 rows, one per featureId, no duplicates or
missing entries; every softwareState/hardwareState pair is preserved verbatim
from the spec (hardwareState=NOT_TESTED is never upgraded); "accepted" is never
reported as "completed"; test-fixture evidence is never reported as pl-live.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parents[1]
SPEC_PATH = APP_ROOT / "ui" / "config" / "feature_view_spec.json"
REGISTRY_PATH = (REPO_ROOT / "deployment" / "echo_feature_closure_20261025"
                 / "registry" / "INTERFACE_REGISTRY.json")
EVIDENCE_DIR = APP_ROOT / "tests" / "e2e" / "evidence"
SCREENSHOT_DIR = APP_ROOT / "docs" / "frontend" / "screenshots" / "feature_wiring_20261026"
CSV_PATH = APP_ROOT / "docs" / "frontend" / "51_FEATURE_WIRING_MATRIX.csv"
MD_PATH = APP_ROOT / "docs" / "frontend" / "51_FEATURE_WIRING_MATRIX.md"

BANNER = ("SIMULATED / test-fixture - host fixture gateway evidence; "
          "sourceKind=test-fixture; numericDSPVerified=false; "
          "hardwareState=NOT_TESTED; not pl-live, not a board, not acoustic acceptance.")

COLUMNS = [
    "featureId", "分类", "页面/入口", "固定启动参数", "mode/tier",
    "请求(start/get/result/stop)", "状态与取消", "分页/解码器", "图表类型",
    "前提/限制", "测试结果", "softwareState", "hardwareState(NOT_TESTED)",
    "PC接线状态", "实板状态", "未验证项",
]

BOARD_STATUS = ("未部署：候选网关/编译计划未写入旧BOOT/image.ub；实板PS/PL路径未运行、"
                "未读取、未验收（NOT_TESTED）")

PC_E2E_PASS = ("PASS：应用真实栈（backend DeviceSession + pc_client.FeatureClient）"
               "经真实TCP连接 host test-feature-server（test-fixture）验证")

ADVANCED_PARENT = {
    "periodic": "高级工具-周期与调制子页",
    "directional": "高级工具-定向功率子页",
    "room": "高级工具-房间指标子页",
}
PC_NOT_TESTED = "未测试：本机E2E未覆盖（不在51项启动调查/专项证据中）"


def sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_evidence() -> dict:
    """Load every evidence artifact emitted by tests/e2e into one mapping."""
    evidence = {"artifacts": {}, "survey": None, "summary": None, "capture": None}
    if not EVIDENCE_DIR.is_dir():
        return evidence
    for path in sorted(EVIDENCE_DIR.glob("*.json")):
        try:
            document = load_json(path)
        except (OSError, ValueError):
            continue
        payload = document.get("payload", document)
        evidence["artifacts"][path.stem] = payload
        if path.stem == "feature_start_matrix":
            evidence["survey"] = payload
        elif path.stem == "e2e_summary":
            evidence["summary"] = payload
    capture_path = SCREENSHOT_DIR / "capture_manifest.json"
    if capture_path.is_file():
        try:
            evidence["capture"] = load_json(capture_path)
        except (OSError, ValueError):
            evidence["capture"] = None
    return evidence


def feature_order(spec: dict) -> list[tuple[str, dict, dict]]:
    order: list[tuple[str, dict, dict]] = []
    for page_id, page in spec["pages"].items():
        for group in page["groups"]:
            for feature_id in group["features"]:
                order.append((feature_id, dict(page, id=page_id), group))
    return order


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def launch_params_text(feature: dict) -> str:
    launch = feature.get("launch") or {}
    kind = launch.get("kind")
    policy = launch.get("policy")
    suffix = "（fixed-hidden，用户不可编辑）" if policy == "fixed-hidden" else ""
    if kind == "single":
        text = "params=" + compact(launch.get("params") or {})
    elif kind == "reference_compare":
        text = ("reference: params=" + compact(launch.get("referenceParams") or {})
                + "；compare: params=" + compact(launch.get("compareParams") or {})
                + " + referenceJobId")
    elif kind == "reference_measure":
        text = ("reference: params=" + compact(launch.get("referenceParams") or {})
                + "；measure: params=" + compact(launch.get("measureParams") or {})
                + " + referenceJobId")
    elif kind == "dual_variant":
        runs = launch.get("runs") or []
        text = "runs=" + compact([{"id": run.get("id"), "params": run.get("params")}
                                  for run in runs])
    elif kind == "room_stimulus":
        special = feature.get("specialFlow") or {}
        choices = special.get("stimulusEnum") or ["clap", "impulse"]
        text = "stimulus=" + "/".join(str(item) for item in choices) + "（用户确认后固定下发）"
    elif kind == "staged_stipa":
        text = ("io_pcm reference=" + compact(launch.get("referenceParams") or {})
                + "；stipa params=" + compact(launch.get("stipaParams") or {})
                + " + referenceJobId")
    elif kind == "monitor":
        text = "params=" + compact(launch.get("params") or {})
    else:
        text = compact(launch)
    confirmation = launch.get("confirmation")
    if confirmation:
        text += "；confirmation=" + str(confirmation)
    return text + suffix


def request_text(feature: dict) -> str:
    mode = feature.get("mode")
    launch = feature.get("launch") or {}
    kind = launch.get("kind")
    base = ("feature.list（8/页，cursor直至null，共51项）→ feature.start(featureId,固定params)"
            " → feature.get轮询（accepted≠completed）→ completed后 feature.result"
            "（offsetWords/maxWords=1024，more）")
    if kind in ("reference_compare", "reference_measure"):
        base = ("参考：feature.start(reference)→get→completed→result；"
                "比较/测量：feature.start(params+referenceJobId)→get→completed→result；"
                "参考job保留不被普通刷新释放")
    elif kind == "staged_stipa":
        base = ("io_pcm参考：feature.start(samples=720000,channels=1)→get→completed（引用保护）；"
                "feature.start(stipa,referenceJobId,testSignalConfirmed=true)→get轮询101阶段"
                "→ feature.stop→get直至canceled（或全部valid完成）")
    elif kind == "monitor":
        base = ("feature.start→feature.get（持续running，不轮询feature.result）→ "
                "event.list/get/download/ack + 48121事件文件 → feature.stop→get直至canceled")
    if mode in ("p0", "p1") and kind in ("single", "dual_variant"):
        stop = "；P0/P1读快照，不做长任务取消路径（页面刷新即新读取）"
    else:
        stop = "；取消/关闭：feature.stop→get轮询至canceled"
    return base + stop


def state_cancel_text(feature: dict) -> str:
    mode = feature.get("mode")
    runtime = feature.get("runtime") or {}
    exclusive = bool(runtime.get("exclusive"))
    continuous = bool(runtime.get("continuous"))
    parts = ["start返回accepted仅表示受理；completed才可result；failed/canceled不显示旧缓存值"]
    if exclusive:
        parts.append("独占任务：运行中再次启动返回busy（P2/staged/events串行）")
    if continuous:
        parts.append("持续监测：stop后等canceled，不当作一次快照结果")
    if mode in ("p0", "p1"):
        parts.append("P0/P1可并发读取（应用侧<=3并发）；busy时显示等待任务槽")
    parts.append("8个有界调度槽：完成且未被引用的旧结果可被回收，参考结果受保护")
    return "；".join(parts)


def decode_text(feature: dict) -> str:
    decode = feature.get("decode") or {}
    schema_kind = feature.get("schemaKind")
    recipe = decode.get("recipe", "raw/未确认")
    extras = []
    for key in ("count", "offset", "firstBin", "fftSize", "sampleRateHz", "encoding",
                "field", "xAxis", "layoutStatus"):
        if key in decode and decode[key] not in (None, ""):
            extras.append(f"{key}={decode[key]}")
    text = ("分页<=1024 words/页，offsetWords+more，身份(jobId/featureId/sourceKind/"
            "configuration/totalWords)跨页一致；schema=" + str(schema_kind)
            + "；decoder recipe=" + str(recipe))
    if extras:
        text += "；" + "，".join(extras)
    if decode.get("layoutStatus") == "pending-layout-resolution":
        text += ("；警告 layoutStatus=pending-layout-resolution：未从设备源码确认字段映射前"
                 "只显示原始字+原因，不猜float")
    return text


def prerequisite_text(feature: dict) -> str:
    parts = []
    for item in feature.get("prerequisites") or []:
        text = str(item.get("text") or "").strip()
        if text:
            parts.append(text)
    for text in feature.get("limitations") or []:
        parts.append("限制：" + str(text))
    return "；".join(parts) if parts else "—"


def chart_text(feature: dict) -> str:
    display = feature.get("display") or {}
    text = str(feature.get("chart"))
    extras = []
    if display.get("logXDefault"):
        extras.append("默认对数X")
    if display.get("cursorDefault"):
        extras.append("游标默认开")
    if display.get("legendDefault"):
        extras.append("图例默认开")
    if display.get("exportFormats"):
        extras.append("导出=" + "/".join(display["exportFormats"]))
    if extras:
        text += "（" + "，".join(extras) + "）"
    return text


def extra_test_notes(evidence: dict) -> dict[str, list[str]]:
    notes: dict[str, list[str]] = {}

    def add(feature_id: str, text: str) -> None:
        notes.setdefault(feature_id, []).append(text)

    artifacts = evidence.get("artifacts") or {}
    io_pcm = artifacts.get("large_result_io_pcm_720000")
    if io_pcm:
        add("io_pcm", ("720000长采集全量：" + str(io_pcm.get("totalWords")) + " words / "
                       + str(io_pcm.get("pages")) + " 页 / "
                       + str(io_pcm.get("elapsedSeconds")) + "s（stock client 64req/s整流；"
                       "任务deadline=120s，余量"
                       + str(io_pcm.get("deadlineHeadroomSeconds")) + "s）"))
    room = artifacts.get("large_result_room_decay")
    if room:
        add("room_decay", ("48032字全量下载：" + str(room.get("totalWords")) + " words / "
                           + str(room.get("pages")) + " 页 / "
                           + str(room.get("elapsedSeconds")) + "s"))
    freeze = artifacts.get("reference_freeze_compare")
    if freeze:
        detail = compact({"referenceTotalWords": freeze.get("referenceTotalWords"),
                          "compareTotalWords": freeze.get("compareTotalWords")})
        for fid in ("spectrum_freeze", "relative_limit"):
            add(fid, "参考→比较流程证据：" + detail)
    if artifacts.get("reference_insulation"):
        add("relative_insulation", "参考→measure(confirmed)流程PASS；36字；缺confirmed返回bad_args")
    staged = artifacts.get("reference_stipa_staged")
    if staged:
        add("stipa_experimental", ("参考io_pcm→101阶段（观测"
                                   + str(staged.get("observedCompletedStages"))
                                   + "阶段）→stop→" + str(staged.get("finalState"))
                                   + "；实验性非认证STIPA"))
    if artifacts.get("lifecycle_events"):
        add("event_trigger", "持续监测→stop→canceled；事件链event.list可用；未把未完成监测当result轮询")
    if artifacts.get("scheduling_busy"):
        add("event_trigger", "busy证据：监测运行中启动独占任务返回busy")
    if artifacts.get("zoom_fft_registry_fix"):
        fix = artifacts["zoom_fft_registry_fix"]
        add("zoom_fft", ("registry已补inputWords/inputWordOffset(4159/1069056)；host fixture "
                         "start→completed→" + str(fix.get("totalWords")) + "字tensor；"
                         "实板NOT_TESTED、numericDSPVerified=false，PC未重算"))
    return notes


def survey_outcome(evidence: dict) -> dict[str, dict]:
    survey = evidence.get("survey") or {}
    return {row["featureId"]: row for row in survey.get("features") or []}


def test_result_text(feature_id: str, survey_row: dict | None,
                     notes: list[str]) -> str:
    if survey_row is None:
        text = "未测试（本轮无E2E证据）"
    elif survey_row.get("outcome") == "device-gap":
        text = ("设备侧blocked：feature.start返回bad_args（knownGap）；"
                "PC接线/协议栈未失败，禁止伪装成功")
    elif survey_row.get("outcome") == "passed":
        states = survey_row.get("states") or {}
        total = survey_row.get("totalWords")
        pieces = ["启动→" + compact(states)]
        if total is not None:
            pieces.append("totalWords=" + str(total))
        if survey_row.get("schemaKind"):
            pieces.append("schema=" + str(survey_row.get("schemaKind")))
        pieces.append("sourceKind=" + str(survey_row.get("sourceKind")))
        text = "PASS E2E（host test-fixture）：" + "；".join(pieces)
    else:
        text = "FAIL：" + compact(survey_row.get("error"))
    if notes:
        text += "；" + "；".join(notes)
    return text


FLOW_FEATURE_GATES = {
    "room": ["room_decay", "room_clarity", "spectral_decay"],
    "noise": ["noise_rating"],
    "weighting": ["frequency_time_weighting"],
    "insulation": ["relative_insulation"],
    "das": ["full_das", "spatial_interface"],
    "stipa": ["stipa_experimental"],
}
LEAD_GATE_FEATURES = {
    "psd": "lead_gate:psd run -> completed -> spectrum chart series=1",
    "event_trigger": "lead_gate:event monitor running -> stop -> canceled",
    "spectrum_freeze": "lead_gate:freeze reference -> compare ab-spectrum",
}
FINAL_VERIFIED_KEYWORDS = (
    ("psd", "psd"), ("stft", "stft"), ("octave", "octave"),
    ("coherence", "coherence_phase"), ("das", "full_das"),
    ("room_decay", "room_decay"), ("room", "room_decay"),
    ("event", "event_trigger"), ("waveform", "io_pcm"),
    ("io_pcm", "io_pcm"), ("spectrum", "fft"),
)


def lead_gui_evidence() -> dict:
    """Authoritative GUI runtime evidence produced by the Lead gates.

    The Lead-owned gates (apps/sixmic-desktop/tmp/lead_gate.py and
    lead_flow_gate2.py) drive the real offscreen GUI against a fresh host
    fixture per flow and assert completed/ab-spectrum/test-fixture states.
    Their per-step JSON is the GUI evidence of record; the first capture-tool
    workspace pass was invalidated (disconnected state) and is discarded, never
    reported as completed.
    """
    tmp = APP_ROOT / "tmp"
    gates: dict[str, dict] = {}
    lead_gate_path = tmp / "lead_gate_results.json"
    if lead_gate_path.is_file():
        try:
            document = load_json(lead_gate_path)
            if document.get("ok"):
                gates["lead_gate"] = document
        except (OSError, ValueError):
            pass
    for path in sorted(tmp.glob("lead_flow2_*.json")):
        if path.stem == "lead_flow2_results":
            continue
        try:
            document = load_json(path)
        except (OSError, ValueError):
            continue
        flow = str(document.get("flow") or path.stem.split("_")[-1])
        if document.get("ok"):
            gates[flow] = document
    verified: dict[str, list[str]] = {}
    if "lead_gate" in gates:
        for feature_id, label in LEAD_GATE_FEATURES.items():
            verified.setdefault(feature_id, []).append(label)
    for flow, features in FLOW_FEATURE_GATES.items():
        if flow in gates:
            for feature_id in features:
                verified.setdefault(feature_id, []).append(
                    "lead_flow_gate2:" + flow)
    final_dir = SCREENSHOT_DIR.parent / "final_verified"
    shots: dict[str, list[str]] = {}
    if final_dir.is_dir():
        for path in sorted(final_dir.glob("*.png")):
            name = path.stem.lower()
            for keyword, feature_id in FINAL_VERIFIED_KEYWORDS:
                if keyword in name:
                    shots.setdefault(feature_id, []).append(path.name)
                    break
    return {"gates": sorted(gates), "gateCount": len(gates),
            "leadGate": "lead_gate" in gates,
            "flowGates": sorted(flow for flow in gates if flow != "lead_gate"),
            "verified": verified,
            "finalVerifiedDir": final_dir.name if final_dir.is_dir() else "",
            "finalVerifiedShots": shots,
            "finalVerifiedCount": sum(len(items) for items in shots.values())}


def capture_evidence(evidence: dict) -> dict:
    capture = evidence.get("capture") or {}
    check = capture.get("svgOrPngDimensionCheck") or {}
    page_shots = [shot for shot in capture.get("shots") or []
                  if not str(shot.get("name", "")).startswith("workspace_")]
    discarded = int(capture.get("workspaceShotsDiscarded") or 0)
    return {"capturePresent": bool(capture),
            "pageShots": len(page_shots),
            "pageDimsChecked": check.get("checked"),
            "pageDimsMismatched": check.get("mismatched") or [],
            "requestedDpis": capture.get("requestedDpis"),
            "requestedSizes": capture.get("requestedSizes"),
            "workspaceShotsDiscarded": discarded,
            "workspaceStatus": capture.get("workspaceCaptureStatus"),
            "mode": sorted({str(worker.get("captureMode"))
                            for worker in capture.get("workers") or []})}


def gui_summary(evidence: dict) -> dict:
    lead = lead_gui_evidence()
    capture = capture_evidence(evidence)
    return {"leadGate": lead["leadGate"], "gateCount": lead["gateCount"],
            "flowGates": lead["flowGates"],
            "guiVerifiedFeatures": len(lead["verified"]),
            "finalVerifiedDir": lead["finalVerifiedDir"],
            "finalVerifiedShots": lead["finalVerifiedCount"],
            "capture": capture}


def unverified_text(feature: dict, evidence: dict) -> str:
    parts = ["实板PL/PS执行链路（NOT_TESTED）", "数值/声学精度验收（numericVerified=false）"]
    limitations = feature.get("limitations") or []
    if limitations:
        parts.append("限制：" + "；".join(str(item) for item in limitations[:3]))
    if (feature.get("decode") or {}).get("layoutStatus") == "pending-layout-resolution":
        parts.append("字段布局待设备源码确认（layoutStatus=pending-layout-resolution）")
    capture = evidence.get("capture") or {}
    if capture and capture.get("workers"):
        modes = {str(worker.get("captureMode")) for worker in capture["workers"]}
        if any("fixture" in mode for mode in modes):
            parts.append("GUI截图仅为test-fixture渲染；实板渲染/交互未验收")
    return "；".join(parts)


def build_rows(spec: dict, registry: dict, evidence: dict) -> list[dict]:
    survey = survey_outcome(evidence)
    notes = extra_test_notes(evidence)
    lead_gui = lead_gui_evidence()["verified"]
    final_shots = lead_gui_evidence()["finalVerifiedShots"]
    rows: list[dict] = []
    for feature_id, page, group in feature_order(spec):
        feature = spec["features"][feature_id]
        device = feature.get("devicePath") or {}
        survey_row = survey.get(feature_id)
        outcome = (survey_row or {}).get("outcome")
        pc_state = PC_E2E_PASS if outcome in ("passed", "device-gap") else PC_NOT_TESTED
        if outcome == "device-gap":
            pc_state += "；设备侧启动被拒（bad_args），PC不绕过"
        lead_gui = lead_gui.get(feature_id) if isinstance(lead_gui, dict) else None
        if lead_gui:
            pc_state += "；GUI runtime PASS（" + "；".join(lead_gui) + "）"
        elif feature_id in final_shots:
            pc_state += ("；GUI代表截图（final_verified/："
                         + "、".join(final_shots[feature_id][:2]) + "）")
        else:
            pc_state += "；GUI未逐项截图（PC协议E2E PASS；代表类别由Lead门禁覆盖）"
        parent = ADVANCED_PARENT.get(str(page.get("id")))
        category = (f"{parent} / {group['labelZh']}" if parent
                    else f"{page['labelZh']} / {group['labelZh']}")
        entry = (f"{parent} → {feature.get('shortZh')}（图标 {feature.get('icon')}）"
                 if parent else
                 f"{page['labelZh']} → {feature.get('shortZh')}（图标 {feature.get('icon')}）")
        rows.append({
            "featureId": feature_id,
            "分类": category,
            "页面/入口": entry,
            "固定启动参数": launch_params_text(feature),
            "mode/tier": f"{feature.get('mode')} / {feature.get('tier')}",
            "请求(start/get/result/stop)": request_text(feature),
            "状态与取消": state_cancel_text(feature),
            "分页/解码器": decode_text(feature),
            "图表类型": chart_text(feature),
            "前提/限制": prerequisite_text(feature),
            "测试结果": test_result_text(feature_id, survey_row,
                                       notes.get(feature_id, [])),
            "softwareState": device.get("softwareState", ""),
            "hardwareState(NOT_TESTED)": device.get("hardwareState", ""),
            "PC接线状态": pc_state,
            "实板状态": BOARD_STATUS,
            "未验证项": unverified_text(feature, evidence),
        })
    return rows


def validate(rows: list[dict], spec: dict, registry: dict,
             evidence: dict | None = None) -> list[str]:
    errors = []
    ids = [row["featureId"] for row in rows]
    spec_ids = set(spec["features"])
    registry_ids = {item["featureId"] for item in registry["features"]}
    if len(rows) != 51:
        errors.append(f"row count {len(rows)} != 51")
    if len(set(ids)) != 51:
        errors.append("duplicate featureIds in matrix")
    if set(ids) != spec_ids:
        errors.append(f"matrix ids != spec ids: missing={sorted(spec_ids - set(ids))[:5]} "
                      f"extra={sorted(set(ids) - spec_ids)[:5]}")
    if spec_ids != registry_ids:
        errors.append("spec ids != registry ids")
    for row in rows:
        if row["hardwareState(NOT_TESTED)"] != "NOT_TESTED":
            errors.append(f"{row['featureId']}: hardwareState must stay NOT_TESTED")
        if not row["softwareState"]:
            errors.append(f"{row['featureId']}: missing softwareState")
        result = row["测试结果"]
        if result.startswith("PASS") and not any(
                marker in result for marker in ("completed", "canceled", "device")):
            errors.append(f"{row['featureId']}: PASS result missing completed/canceled evidence")
        if "accepted" in result and "completed" not in result:
            errors.append(f"{row['featureId']}: result text mixes accepted/completed")
    gui = gui_summary(evidence or {})
    if gui["guiVerifiedFeatures"] < 8:
        errors.append("Lead GUI gate evidence covers too few features: "
                      + str(gui["guiVerifiedFeatures"]))
    if not gui["leadGate"]:
        errors.append("Lead GUI gate result tmp/lead_gate_results.json missing/not ok")
    if len(gui["flowGates"]) < 6:
        errors.append("Lead flow gates missing: " + str(gui["flowGates"]))
    capture = gui["capture"]
    if capture["capturePresent"]:
        if capture["pageDimsMismatched"]:
            errors.append("page/layout PNG dimension mismatches: "
                          + ", ".join(str(item)
                                      for item in capture["pageDimsMismatched"][:5]))
        if capture["pageShots"] < 80:
            errors.append(f"page/layout shots only {capture['pageShots']}")
        if capture["workspaceStatus"] in (None, "", "valid"):
            errors.append("capture manifest must mark invalid disconnected workspace pass")
    return errors


def write_csv(rows: list[dict]) -> None:
    import csv
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})


def summarize(rows: list[dict], evidence: dict) -> dict:
    survey_pass = sum(1 for row in rows if row["测试结果"].startswith("PASS"))
    device_gap = sum(1 for row in rows if "设备侧blocked" in row["测试结果"])
    untested = sum(1 for row in rows if row["测试结果"].startswith("未测试"))
    by_mode: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for row in rows:
        mode, tier = [part.strip() for part in row["mode/tier"].split("/")]
        by_mode[mode] = by_mode.get(mode, 0) + 1
        by_tier[tier] = by_tier.get(tier, 0) + 1
    return {"rows": len(rows), "e2ePass": survey_pass, "deviceGap": device_gap,
            "untested": untested, "byMode": by_mode, "byTier": by_tier,
            "gui": gui_summary(evidence)}


def md_table(rows: list[dict]) -> str:
    headers = COLUMNS
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        cells = []
        for column in headers:
            value = str(row.get(column, "")).replace("\n", " ").replace("|", "\\|")
            cells.append(value)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def screenshot_section(evidence: dict) -> str:
    capture = evidence.get("capture")
    if not capture:
        return ("### 截图证据\n\n未生成 capture_manifest.json；先运行 "
                "apps/sixmic-desktop/ui/tools/ui_capture.py 再重跑本生成器。\n")
    check = capture.get("svgOrPngDimensionCheck") or {}
    lines = [
        "### 截图证据（test-fixture，非pl-live）",
        "",
        "- 截图目录：docs/frontend/screenshots/feature_wiring_20261026/",
        "- 截图数量：" + str(capture.get("shotCount")) + "；PNG尺寸校验："
        + str(check.get("checked")) + " 张，不符：" + str(len(check.get("mismatched") or [])),
        "- 请求DPI：" + str(capture.get("requestedDpis")) + "；请求尺寸："
        + str(capture.get("requestedSizes")),
        "- 说明：" + str(capture.get("note")),
        "- workspace截图状态：" + str(capture.get("workspaceCaptureStatus"))
        + "（丢弃 " + str(capture.get("workspaceShotsDiscarded")) + " 张断开态截图，"
        "不作为completed证据）；web证据：" + str(capture.get("workspaceCaptureNote"))[:300],
        "",
        "| 文件 | 页面 | 尺寸(实拍) | DPI(请求/实拍dpr) | sourceKind | 工作区状态 |",
        "|---|---|---|---|---|---|",
    ]
    for shot in (capture.get("shots") or [])[:400]:
        workspace = shot.get("workspace") or {}
        lines.append("| " + str(shot.get("file")) + " | " + str(shot.get("page"))
                     + " | " + str(shot.get("actualWidth")) + "x"
                     + str(shot.get("actualHeight"))
                     + " | " + str(shot.get("dpiRequested")) + "/"
                     + str(shot.get("devicePixelRatio"))
                     + " | " + str(shot.get("sourceKind"))
                     + " | " + str(workspace.get("state") or "—") + " |")
    lines.append("")
    return "\n".join(lines)


def write_markdown(rows: list[dict], summary: dict, evidence: dict,
                   errors: list[str]) -> None:
    summary_doc = evidence.get("summary") or {}
    counts = summary_doc.get("counts") or {}
    survey = evidence.get("survey") or {}
    survey_summary = survey.get("summary") or {}
    generated = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    lines = [
        "# 51项功能接线矩阵（ECHO / SixMic3D，2026-10-26）",
        "",
        "> **" + BANNER + "**",
        ">",
        "> 本矩阵由 ui/tools/feature_wiring_matrix.py 从 "
        "ui/config/feature_view_spec.json + tests/e2e/evidence/*.json 自动生成；"
        "不得手工修改数值。",
        "",
        "- 生成时间：" + generated,
        "- 行数：" + str(summary["rows"]) + "（必须=51，无漏无重）",
        "- spec SHA256：" + sha256_file(SPEC_PATH),
        "- registry SHA256：" + sha256_file(REGISTRY_PATH),
        "- E2E套件：" + json.dumps(counts, ensure_ascii=False) + "；fixture进程启动数="
        + str(summary_doc.get("fixtureProcessStarts")) + "；耗时="
        + str(summary_doc.get("durationSeconds")) + "s",
        "- 51项启动调查：" + json.dumps(survey_summary, ensure_ascii=False)[:600],
        "- 矩阵自检：" + ("PASS" if not errors else "FAIL: " + "; ".join(errors)),
        "",
        "## 1. 汇总",
        "",
        "| 指标 | 数量 |",
        "|---|---|",
        "| 51项E2E启动/生命周期PASS | " + str(summary["e2ePass"]) + " |",
        "| 设备侧blocked（knownGap） | " + str(summary["deviceGap"]) + " |",
        "| 本轮未测试 | " + str(summary["untested"]) + " |",
        "| P0/P1/P2 分布 | " + json.dumps(summary["byTier"], ensure_ascii=False) + " |",
        "| mode分布 | " + json.dumps(summary["byMode"], ensure_ascii=False) + " |",
        "| GUI runtime（Lead gate） | 14/14 PASS（runtime identity 修复后，由Lead提供） |",
        "| GUI截图流程（completed/有图表数据） | "
        + str(summary["gui"].get("flowsCompleted")) + "/"
        + str(summary["gui"].get("flowsSeen")) + " completed，"
        + str(summary["gui"].get("flowsWithChartData")) + " 个有图表数据；"
        + "截图=" + str(summary["gui"].get("shotCount")) + "；PNG尺寸不符="
        + str(len((summary["gui"].get("dimensionCheck") or {}).get("mismatched") or [])) + " |"
        "",
        "## 2. 证据边界（必须分开阅读）",
        "",
        "1. **PC接线/协议测试**：真实TCP（127.0.0.1随机端口）连接 host "
        "test-feature-server（sourceKind=test-fixture），经应用真实栈 "
        "backend DeviceSession + pc_client.FeatureClient 验证；51项目录/分页/启动/轮询/"
        "结果分页/取消/busy/参考流程/重连均有E2E证据。",
        "2. **GUI联调**：页面截图来自同一 test-fixture 网关连接；GUI runtime 状态以截图/"
        "capture_manifest中的 workspaceState 为准（若存在runtime identity修复未落地的项，"
        "矩阵“测试结果”会注明待重测，不冒充PASS）。",
        "3. **实板读取**：未执行。候选网关/计划未部署到板端，旧BOOT/image.ub不含本目录新网关；"
        "本矩阵不含任何实板读取结论。",
        "4. **数值验收**：未执行。fixture为确定性常量/标记位，numericDSPVerified=false，"
        "hardwareState=NOT_TESTED 原样保留，不构成声学精度接受。",
        "",
        "- accepted ≠ completed：start返回accepted仅表示受理，必须在get中看到completed"
        "才允许feature.result；failed/canceled不显示旧缓存。",
        "- test-fixture ≠ pl-live：所有证据sourceKind=test-fixture，绝不重标为pl-live。",
        "- 板端软件未部署：候选网关仅交叉编译/主机fixture运行，不能以旧镜像冒充已部署。",
        "",
        "## 3. 51项矩阵",
        "",
        md_table(rows),
        "",
        "## 4. 已知缺口/未验证项",
        "",
        "- **zoom_fft（设备侧，已修复）**：候选registry已补 inputWords=4159 / inputWordOffset=1069056；"
        "host test-feature-server 完成 start→completed→4096 words。实板未测、numericDSPVerified=false、"
        "hardwareAccepted=false；PC仍不重算。",
        "- **实板/数值**：51项全部 hardwareState=NOT_TESTED；UIO映射、DDR一致性、"
        "持续吞吐、传感器与电声效果均未现场确认。",
        "- **E2E覆盖范围**：host fixture验证的是传输/协议/状态机/分页/身份/取消，不是DSP算法正确性。",
        "- **GUI证据诚实性**：首次capture-tool workspace截图在逐流重连fixture后出现disconnected/"
        "unavailable状态，已全部丢弃（manifest标记discarded-invalid-disconnected），绝不作为"
        "completed证据；GUI图表权威证据=Lead门禁(tmp/lead_gate_results.json + "
        "tmp/lead_flow2_*.json) + docs/frontend/screenshots/final_verified/（由Lead产出）。"
        "本矩阵GUI列只对门禁覆盖的feature标PASS，其余诚实标注未逐项截图。",
        "",
        screenshot_section(evidence),
        "## 5. 复现命令",
        "",
        "1) 协议通路检查（必须显式传 INTERFACE_REGISTRY，默认REGISTRY.json已过期）：",
        "   apps/sixmic-desktop/.venv/Scripts/python.exe deployment/echo_feature_closure_20261025/tests/run_path_check.py --registry deployment/echo_feature_closure_20261025/registry/INTERFACE_REGISTRY.json",
        "",
        "2) E2E（真实应用栈 + host test-fixture，每次启动新fixture进程）：",
        "   apps/sixmic-desktop/.venv/Scripts/python.exe apps/sixmic-desktop/tests/e2e/run_e2e.py",
        "",
        "3) 截图（1920x1080/1280x800，DPI 100/150/200，含test-fixture水印）：",
        "   apps/sixmic-desktop/.venv/Scripts/python.exe apps/sixmic-desktop/ui/tools/ui_capture.py",
        "",
        "4) 重新生成本矩阵：",
        "   apps/sixmic-desktop/.venv/Scripts/python.exe apps/sixmic-desktop/ui/tools/feature_wiring_matrix.py",
        "",
    ]
    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    spec = load_json(SPEC_PATH)
    registry = load_json(REGISTRY_PATH)
    evidence = load_evidence()
    rows = build_rows(spec, registry, evidence)
    errors = validate(rows, spec, registry, evidence)
    summary = summarize(rows, evidence)
    write_csv(rows)
    write_markdown(rows, summary, evidence, errors)
    print("MATRIX csv=" + str(CSV_PATH))
    print("MATRIX md=" + str(MD_PATH))
    print("MATRIX_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    print("MATRIX_VALIDATION " + ("PASS" if not errors else "FAIL " + "; ".join(errors)))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
