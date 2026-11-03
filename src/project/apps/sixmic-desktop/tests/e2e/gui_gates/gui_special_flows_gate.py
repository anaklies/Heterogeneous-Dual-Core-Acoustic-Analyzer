
"""Lead special-flow GUI gate with a FRESH fixture per flow (60s fixture lifetime)."""
import json, os, subprocess, sys, time
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(r"C:\Users\sunxi\Desktop\sixmic3D"); APP = ROOT/"apps"/"sixmic-desktop"
os.environ.update({"QT_QPA_PLATFORM":"offscreen","QT_QUICK_BACKEND":"software",
  "QT_QPA_FONTDIR":r"C:\Windows\Fonts","SIXMIC_DISABLE_UI_SCALE":"1",
  "SIXMIC_USER_DATA_DIR":str(APP/"tmp"/"lead_flow2_userdata")})
sys.path.insert(0, str(APP)); sys.path.insert(0, str(APP/"backend"))
REG = ROOT/"deployment/echo_feature_closure_20261025/registry/INTERFACE_REGISTRY.json"
PROFILE = ROOT/"deployment/echo_feature_closure_20261025/ps/profiles/default/profile_init.smi"
EXE = ROOT/"deployment/echo_feature_closure_20261025/ps/build/host/test-feature-server.exe"
SPOOL_ROOT = APP/"tmp"/"lead_flow2_spool"
res = {"steps": {}, "failures": []}
def check(name, ok, detail=""):
    res["steps"][name] = {"ok": bool(ok), "detail": detail}
    if not ok: res["failures"].append(name + ": " + str(detail))
    print(("PASS " if ok else "FAIL ") + name + (" :: " + str(detail) if detail else ""), flush=True)

import main as appmain
application, engine, bridge, vm, theme, images, qml = appmain.create_application()
def pump(sec):
    end=time.monotonic()+sec
    while time.monotonic()<end: application.processEvents(); time.sleep(0.02)
def wait(pred, timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        application.processEvents()
        try:
            if pred(): return True
        except Exception: pass
        time.sleep(0.05)
    return False
ws = lambda: vm.featureWorkspace
chart = lambda: (vm.featureWorkspace.get("chart") or {})
variants = lambda: (vm.featureWorkspace.get("variants") or [])
pump(0.5)

class Fixture:
    def __init__(self):
        SPOOL_ROOT.mkdir(parents=True, exist_ok=True)
        self.spool = SPOOL_ROOT / str(int(time.time()*1000)%100000)
        self.spool.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen([str(EXE),str(REG),str(PROFILE),str(self.spool)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.ready = json.loads(self.proc.stdout.readline())
    def connect(self):
        vm.connectDevice("127.0.0.1", self.ready["controlPort"], self.ready["binaryPort"])
        ok = wait(lambda: vm.connectionState=="connected", 10)
        vm.claimControl(); pump(0.6)
        ok = ok and wait(lambda: vm.featureStatus.get("catalogComplete") is True, 12)
        return ok
    def close(self):
        try: vm.disconnectDevice(); pump(0.4)
        except Exception: pass
        self.proc.terminate()
        try:
            out,err = self.proc.communicate(timeout=5)
            if err.strip(): res.setdefault("server_stderr",[]).append(err[-300:])
        except Exception: pass

def with_fixture(name, fn):
    fx = Fixture()
    try:
        if not fx.connect():
            check(name + "_fixture_connect", False, vm.connectionState)
            return
        fn()
    except Exception as exc:
        check(name + "_exception", False, f"{type(exc).__name__}: {exc}")
    finally:
        fx.close()

def flow_room():
    vm.openFeatureEntry("room_decay"); pump(0.3)
    vm.runFeature("room_decay"); pump(0.8)
    confirmations = (ws().get("flow") or {}).get("confirmations") or []
    stimulus = next((c for c in confirmations if c.get("id")=="stimulus"), None)
    check("room_stimulus_confirmation_present", ws().get("state") in ("idle","blocked") and stimulus is not None,
          {"state": ws().get("state"), "options": [o.get("value") for o in (stimulus or {}).get("options") or []]})
    vm.featureConfirm("room_decay","stimulus","clap"); pump(0.2)
    vm.runFeature("room_decay")
    ok = wait(lambda: ws().get("state")=="completed" and chart().get("kind")=="room-decay", 30)
    pump(0.4)
    check("room_decay_run_completed", ok and len(chart().get("series") or [])+len(chart().get("panels") or [])>0,
          {"state": ws().get("state"), "series": len(chart().get("series") or []),
           "notes": (ws().get("notes") or [])[:2]})

def flow_noise():
    vm.openFeatureEntry("noise_rating"); pump(0.3)
    vm.featureConfirm("noise_rating","referenceConfirmed",True); pump(0.2)
    vm.runFeature("noise_rating")
    ok = wait(lambda: len([v for v in variants() if v.get("state")=="completed"]) >= 2, 30)
    labels = [v.get("label") for v in variants()]
    check("noise_rating_dual_variants", ok and len(set(labels))==2,
          {"labels": labels, "kinds": [(v.get("chart") or {}).get("kind") for v in variants()]})

def flow_weighting():
    vm.openFeatureEntry("frequency_time_weighting"); pump(0.3)
    vm.runFeature("frequency_time_weighting")
    ok = wait(lambda: len([v for v in variants() if v.get("state")=="completed"]) >= 2, 40)
    payload_sizes = [len((v.get("chart") or {}).get("series") or []) + len((v.get("chart") or {}).get("panels") or [])
                     for v in variants()]
    check("weighting_dual_separate", ok and len(variants())==2,
          {"labels": [v.get("label") for v in variants()], "sizes": payload_sizes})
    check("weighting_charts_present", all(size>0 for size in payload_sizes), payload_sizes)

def flow_insulation():
    vm.openFeatureEntry("relative_insulation"); pump(0.3)
    vm.runFeature("relative_insulation")
    ref_ok = wait(lambda: (ws().get("references") or {}).get("hasReference") is True, 40)
    check("insulation_reference", ref_ok, {"state": ws().get("state"),
          "refs": ws().get("references")})
    vm.featureConfirm("relative_insulation","chain-confirm",True); pump(0.5)
    vm.runFeature("relative_insulation")
    ok = wait(lambda: ws().get("state")=="completed" and chart().get("kind")=="insulation-bars", 40)
    pump(0.5)
    size = len(chart().get("categories") or []) + len(chart().get("series") or []) + len(chart().get("panels") or [])
    check("insulation_measure_completed", ok and size>0,
          {"state": ws().get("state"), "kind": chart().get("kind"), "size": size,
           "categories": len(chart().get("categories") or [])})

def flow_das():
    vm.openFeatureEntry("full_das"); pump(0.3)
    vm.runFeature("full_das")
    ok = wait(lambda: ws().get("state")=="completed" and chart().get("kind")=="das-map"
              and len(chart().get("imageUrl") or "")>0, 40)
    pump(0.4)
    ch = chart()
    check("full_das_map", ok and len(ch.get("imageUrl") or "")>0,
          {"kind": ch.get("kind"), "imageUrl": (ch.get("imageUrl") or "")[:50],
           "markers": len(ch.get("markers") or []), "notes": (ws().get("notes") or [])[:2]})
    vm.closeFeatureWorkspace(); pump(0.2)
    vm.openFeatureEntry("spatial_interface"); pump(0.3)
    vm.runFeature("spatial_interface")
    ok = wait(lambda: ws().get("state")=="completed" and chart().get("kind")=="capability"
              and len(chart().get("text") or "")>0, 20)
    check("spatial_interface_capability", ok, {"text": (chart().get("text") or "")[:80]})

def flow_stipa():
    vm.openFeatureEntry("stipa_experimental"); pump(0.4)
    check("stipa_available", ws().get("available") is True, ws().get("disabledReason"))
    # stage 1: run captures the io_pcm 720000-sample known reference
    vm.runFeature("stipa_experimental")
    ref_ok = wait(lambda: (ws().get("references") or {}).get("hasReference") is True, 60)
    check("stipa_reference_captured", ref_ok,
          {"state": ws().get("state"), "refs": ws().get("references")})
    # stage 2: explicit test-signal confirmation then start the 101-stage graph
    vm.featureConfirm("stipa_experimental","testSignalConfirmed",True); pump(0.5)
    vm.runFeature("stipa_experimental")
    started = wait(lambda: ws().get("state") in ("running","queued","accepted"), 20)
    progress_ok = wait(lambda: int(((ws().get("flow") or {}).get("stages") or {}).get("completed") or 0) >= 2, 60)
    stages = ((ws().get("flow") or {}).get("stages") or {})
    check("stipa_stages_progress", started and progress_ok,
          {"state": ws().get("state"), "stages": stages})
    vm.stopFeature("stipa_experimental")
    ok = wait(lambda: ws().get("state")=="canceled", 30)
    check("stipa_stop_canceled", ok, ws().get("state"))

FLOWS = {"room": flow_room, "noise": flow_noise, "weighting": flow_weighting,
         "insulation": flow_insulation, "das": flow_das, "stipa": flow_stipa}
flow_name = sys.argv[1] if len(sys.argv) > 1 else ""
if flow_name not in FLOWS:
    print("usage: lead_flow_gate2.py " + "|".join(FLOWS), flush=True)
    raise SystemExit(2)
with_fixture(flow_name, FLOWS[flow_name])
qml_errors = appmain._collect_qml_errors(engine)
check("qml_warnings_zero", len(qml_errors)==0, qml_errors[:3])
vm.prepareExit(); pump(0.3); bridge.shutdown(); pump(0.2)
res["ok"] = not res["failures"]
res["flow"] = flow_name
(APP/"tmp"/("lead_flow2_" + flow_name + ".json")).write_text(
    json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("RESULT", "PASS" if res["ok"] else "FAIL", len(res["failures"]), "failures", flush=True)
raise SystemExit(0 if res["ok"] else 1)