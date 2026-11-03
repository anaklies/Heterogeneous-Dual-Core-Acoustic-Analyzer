
"""Lead integration gate: offscreen GUI stack + real FeatureRuntime -> host gateway."""
import json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(r"C:\Users\sunxi\Desktop\sixmic3D")
APP = ROOT/"apps"/"sixmic-desktop"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
os.environ["SIXMIC_DISABLE_UI_SCALE"] = "1"
os.environ["SIXMIC_USER_DATA_DIR"] = str(APP/"tmp"/"lead_gate_userdata")
sys.path.insert(0, str(APP)); sys.path.insert(0, str(APP/"backend"))
REG = ROOT/"deployment/echo_feature_closure_20261025/registry/INTERFACE_REGISTRY.json"
PROFILE = ROOT/"deployment/echo_feature_closure_20261025/ps/profiles/default/profile_init.smi"
EXE = ROOT/"deployment/echo_feature_closure_20261025/ps/build/host/test-feature-server.exe"
SPOOL = APP/"tmp"/"lead_gate_spool"; SPOOL.mkdir(parents=True, exist_ok=True)
for sub in ("root","logs","data","recordings","events","exports","evidence"):
    (SPOOL/sub).mkdir(parents=True, exist_ok=True)

proc = subprocess.Popen([str(EXE), str(REG), str(PROFILE), str(SPOOL)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
results = {"steps": {}, "failures": []}
def check(name, ok, detail=""):
    results["steps"][name] = {"ok": bool(ok), "detail": detail}
    if not ok:
        results["failures"].append(name + ": " + str(detail))
    print(("PASS " if ok else "FAIL ") + name + (" :: " + str(detail) if detail else ""))
try:
    ready = json.loads(proc.stdout.readline())
    import main as appmain
    application, engine, bridge, vm, theme, images, qml = appmain.create_application()
    def pump(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            application.processEvents(); time.sleep(0.02)
    def pump_until(predicate, timeout=15.0, step=0.05):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            application.processEvents()
            try:
                if predicate(): return True
            except Exception: pass
            time.sleep(step)
        application.processEvents()
        return False
    pump(0.5)
    vm.connectDevice("127.0.0.1", ready["controlPort"], ready["binaryPort"])
    connected = pump_until(lambda: vm.connectionState == "connected", 10)
    check("connect_host_gateway", connected, vm.connectionState)
    vm.claimControl(); pump(0.8)
    check("control_claim", bool(vm.controlHeld), vm.controlHeld)
    status = vm.featureStatus
    catalog_ready = pump_until(lambda: vm.featureStatus.get("catalogComplete") is True
                               or len(vm.featureEntriesForPage("spectrum")) > 0
                               and vm.featureEntriesForPage("spectrum")[0].get("available") is True, 12)
    status = vm.featureStatus
    check("feature_api_enabled", status.get("featureApiEnabled") is True, json.dumps(status, ensure_ascii=False)[:400])
    entries = vm.featureEntriesForPage("spectrum")
    check("catalog_51_entries_total", sum(len(vm.featureEntriesForPage(p)) for p in
          ("time","spectrum","bands","periodic","multichannel","directional","events","room")) == 51,
          len(entries))
    check("entries_available", bool(entries) and entries[0].get("available") is True,
          json.dumps(entries[:1], ensure_ascii=False)[:300])
    groups = vm.featureGroupsForPage("spectrum")
    check("groups_8_category_layout", [g["label"] for g in groups] == ["频谱及比较"], [g["label"] for g in groups])

    # --- single feature run (psd) -------------------------------------
    vm.openFeatureEntry("psd"); pump(0.3)
    check("workspace_open", vm.featureWorkspace.get("open") is True and vm.featureWorkspace.get("featureId") == "psd",
          vm.featureWorkspace.get("featureId"))
    vm.runFeature("psd")
    done = pump_until(lambda: vm.featureWorkspace.get("state") in ("completed","failed","canceled"), 25)
    pump_until(lambda: len((vm.featureWorkspace.get("chart") or {}).get("series") or []) > 0
               or vm.featureWorkspace.get("state") in ("failed","canceled"), 15)
    ws = vm.featureWorkspace
    check("psd_run_completed", done and ws.get("state") == "completed", ws.get("state"))
    check("psd_chart", (ws.get("chart") or {}).get("kind") == "spectrum" and len((ws.get("chart") or {}).get("series") or []) >= 1,
          {"kind": (ws.get("chart") or {}).get("kind"), "series": len((ws.get("chart") or {}).get("series") or [])})
    check("psd_source_test_fixture", ws.get("sourceKind") == "test-fixture", ws.get("sourceKind"))
    check("workspace_no_params", "params" not in ws and "paramForm" not in ws, list(ws.keys())[:12])
    check("psd_units", bool(ws.get("units")), ws.get("units"))

    # --- event monitor flow -------------------------------------------
    vm.openFeatureEntry("event_trigger"); pump(0.3)
    vm.runFeature("event_trigger"); pump(2.0)
    ws = vm.featureWorkspace
    running = ws.get("state") in ("running","accepted","starting","queued")
    check("event_trigger_running", running, ws.get("state"))
    vm.stopFeature("event_trigger")
    canceled = pump_until(lambda: vm.featureWorkspace.get("state") == "canceled", 12)
    check("event_trigger_stop_canceled", canceled, vm.featureWorkspace.get("state"))

    # --- reference / compare flow --------------------------------------
    vm.openFeatureEntry("spectrum_freeze"); pump(0.3)
    vm.runFeature("spectrum_freeze")
    ref_done = pump_until(lambda: vm.featureWorkspace.get("state") == "completed", 25)
    pump_until(lambda: (vm.featureWorkspace.get("references") or {}).get("hasReference") is True
               or vm.featureWorkspace.get("state") == "failed", 15)
    ws = vm.featureWorkspace
    refs = ws.get("references") or {}
    check("freeze_reference_completed", ref_done and refs.get("hasReference") is True,
          {"state": ws.get("state"), "refs": refs})
    actions = [(a.get("id"), a.get("enabled")) for a in ((ws.get("flow") or {}).get("actions") or [])]
    check("freeze_compare_action_present", any(aid == "compare" for aid, _ in actions), actions)
    vm.featureAction("spectrum_freeze", "compare")
    cmp_done = pump_until(lambda: vm.featureWorkspace.get("state") == "completed"
                          and (vm.featureWorkspace.get("chart") or {}).get("kind") == "ab-spectrum", 25)
    ws = vm.featureWorkspace
    check("freeze_compare_chart", cmp_done, {"state": ws.get("state"), "kind": (ws.get("chart") or {}).get("kind")})

    # close + capture QML warnings
    vm.closeFeatureWorkspace(); pump(0.3)
    qml_errors = appmain._collect_qml_errors(engine)
    check("qml_warnings_zero", len(qml_errors) == 0, qml_errors[:4])
    vm.prepareExit(); pump(0.3)
    bridge.shutdown(); pump(0.2)
finally:
    proc.terminate()
    try:
        out, err = proc.communicate(timeout=5)
        if err.strip():
            results["server_stderr_tail"] = err[-800:]
    except Exception: pass
results["ok"] = not results["failures"]
(APP/"tmp"/"lead_gate_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print("RESULT", "PASS" if results["ok"] else "FAIL", len(results["failures"]), "failures")
