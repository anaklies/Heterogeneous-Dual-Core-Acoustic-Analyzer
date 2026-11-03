
"""Authoritative final visual evidence: real GUI runs against host fixture.

Only captures a workspace when the live assertions hold (connected, expected
state, sourceKind, chart payload).  Fresh fixture + fresh user data per batch so
the 60s fixture lifetime cannot silently drop the gateway mid-capture.
"""
import json, os, subprocess, sys, time
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(r"C:\Users\sunxi\Desktop\sixmic3D"); APP = ROOT/"apps"/"sixmic-desktop"
OUT = APP/"docs"/"frontend"/"screenshots"/"final_verified"; OUT.mkdir(parents=True, exist_ok=True)
batch = sys.argv[1] if len(sys.argv) > 1 else "A"
width = int(sys.argv[2]) if len(sys.argv) > 2 else 1920
height = int(sys.argv[3]) if len(sys.argv) > 3 else 1080
scale = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
stamp = time.strftime("%H%M%S")
user_dir = APP/"tmp"/f"lead_final_capture_{batch}_{stamp}"
(user_dir/"ui").mkdir(parents=True, exist_ok=True)
(user_dir/"ui"/"ui_settings.json").write_text(json.dumps({
    "windowWidth": width, "windowHeight": height, "windowMaximized": False,
    "language": "zh", "themeMode": "dark"}), encoding="utf-8")
os.environ.update({"QT_QPA_PLATFORM":"offscreen","QT_QUICK_BACKEND":"software",
  "QT_QPA_FONTDIR":r"C:\Windows\Fonts","SIXMIC_DISABLE_UI_SCALE":"1",
  "SIXMIC_USER_DATA_DIR":str(user_dir)})
if abs(scale - 1.0) > 1e-6:
    os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
sys.path.insert(0, str(APP)); sys.path.insert(0, str(APP/"backend"))
REG = ROOT/"deployment/echo_feature_closure_20261025/registry/INTERFACE_REGISTRY.json"
PROFILE = ROOT/"deployment/echo_feature_closure_20261025/ps/profiles/default/profile_init.smi"
EXE = ROOT/"deployment/echo_feature_closure_20261025/ps/build/host/test-feature-server.exe"
SPOOL = APP/"tmp"/f"lead_final_spool_{batch}_{stamp}"; SPOOL.mkdir(parents=True, exist_ok=True)
proc = subprocess.Popen([str(EXE),str(REG),str(PROFILE),str(SPOOL)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
shots, failures = [], []
def fail(name, why):
    failures.append(name + ": " + str(why)); print("FAIL", name, why, flush=True)
def record(name, feature_id, page_id, kind, note):
    pump(0.5)
    try: vm.dismissToast()
    except Exception: pass
    pump(0.3)
    image = window.grabWindow()
    suffix = f"{width}x{height}_dpi{int(round(scale*100))}"
    path = OUT / f"{name}_{suffix}.png"; image.save(str(path), "PNG")
    ws = vm.featureWorkspace
    item = {"name": name + "_" + suffix, "file": path.name,
            "width": image.width(), "height": image.height(),
            "page": page_id, "featureId": feature_id, "chartKind": (ws.get("chart") or {}).get("kind"),
            "workspaceState": ws.get("state"), "sourceKind": ws.get("sourceKind"),
            "connected": vm.connectionState == "connected",
            "series": len((ws.get("chart") or {}).get("series") or []),
            "panels": len((ws.get("chart") or {}).get("panels") or []),
            "imageUrl": bool((ws.get("chart") or {}).get("imageUrl")),
            "dpiScale": scale, "note": note,
            "fixture": True, "hardwareState": "NOT_TESTED"}
    shots.append(item)
    print("SHOT", name, image.width(), image.height(), ws.get("state"),
          item["chartKind"], flush=True)
try:
    ready = json.loads(proc.stdout.readline())
    import main as appmain
    application, engine, bridge, vm, theme, images, qml = appmain.create_application()
    window = engine.rootObjects()[-1]
    def pump(sec):
        end=time.monotonic()+sec
        while time.monotonic()<end: application.processEvents(); time.sleep(0.02)
    def wait(pred, timeout=45):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            application.processEvents()
            try:
                if pred(): return True
            except Exception: pass
            time.sleep(0.05)
        return False
    def assert_workspace(expected_states, kind=None, need_image=False, need_payload=False):
        ws = vm.featureWorkspace; ch = ws.get("chart") or {}
        if vm.connectionState != "connected":
            return False, "not connected"
        if ws.get("state") not in expected_states:
            return False, "state=" + str(ws.get("state"))
        if ws.get("sourceKind") not in ("test-fixture",):
            return False, "sourceKind=" + str(ws.get("sourceKind"))
        if kind and ch.get("kind") != kind:
            return False, "kind=" + str(ch.get("kind"))
        if need_image and not ch.get("imageUrl"):
            return False, "missing raster imageUrl"
        if need_payload:
            size = (len(ch.get("series") or []) + len(ch.get("panels") or [])
                    + len(ch.get("categories") or []) + len(ch.get("scalarRows") or [])
                    + len(ch.get("channels") or []) + len(ch.get("meters") or [])
                    + len(ch.get("events") or []) + len(ch.get("frames") or []))
            if size <= 0 and not ch.get("text") and not ch.get("imageUrl"):
                return False, "empty chart payload"
        return True, "ok"
    def run(feature_id, page_id, state="completed", kind=None, need_image=False,
            need_payload=True, name=None, note="", timeout=45, confirm=None):
        vm.setCurrentPage(page_id); pump(0.3)
        vm.openFeatureEntry(feature_id); pump(0.4)
        if confirm:
            for key, value in confirm.items():
                vm.featureConfirm(feature_id, key, value)
            pump(0.3)
        vm.runFeature(feature_id)
        ok = wait(lambda: vm.featureWorkspace.get("state") in (state, "failed", "canceled"), timeout)
        if kind:
            wait(lambda: (vm.featureWorkspace.get("chart") or {}).get("kind") == kind, 20)
        pump(0.8)
        good, why = assert_workspace((state,), kind, need_image, need_payload)
        if not good:
            fail(name or feature_id, why); return False
        if name:
            record(name, feature_id, page_id, kind, note)
        return True
    def window_size_ok():
        got = (int(window.property("width")), int(window.property("height")))
        if got == (width, height):
            return True
        window.setProperty("width", width); window.setProperty("height", height)
        pump(1.0)
        got = (int(window.property("width")), int(window.property("height")))
        print("window requested", (width, height), "got", got, flush=True)
        return got == (width, height)
    pump(0.5)
    vm.connectDevice("127.0.0.1", ready["controlPort"], ready["binaryPort"])
    if not wait(lambda: vm.connectionState == "connected", 12):
        raise SystemExit("connect failed")
    vm.claimControl(); pump(0.8)
    if not wait(lambda: vm.featureStatus.get("catalogComplete") is True, 15):
        raise SystemExit("catalog incomplete")
    if not window_size_ok():
        raise SystemExit("window size mismatch")
    print("BATCH", batch, "window", window.property("width"), window.property("height"), flush=True)

    if batch == "A":
        run("psd","spectrum",kind="spectrum",name="workspace_spectrum_psd_completed",
            note="Welch PSD from PL result (test fixture)")
        run("stft","spectrum",kind="stft",need_image=True,
            name="workspace_spectrum_stft_2d_completed",
            note="STFT retained PL frames: 2D Viridis heatmap with colorbar")
        # 3D waterfall view of the same completed result
        host = window.findChild(type(window), "chartStftHost") if False else None
        from PySide6.QtQuick import QQuickItem
        host = window.findChild(QQuickItem, "chartStftHost")
        chart_root = None
        if host is not None:
            item = host
            for _ in range(6):
                if item is None: break
                if item.property("threeDActive") is not None:
                    chart_root = item; break
                item = item.parentItem()
        if chart_root is not None:
            chart_root.setProperty("threeDActive", True); pump(1.2)
            good, why = assert_workspace(("completed",), "stft")
            if good:
                record("workspace_spectrum_stft_3d_completed", "stft", "spectrum", "stft",
                       "STFT 3D waterfall view of retained frames (display toggle only)")
            else:
                fail("stft_3d", why)
            chart_root.setProperty("threeDActive", False); pump(0.4)
        else:
            fail("stft_3d", "toggle not found")
        run("octave","bands",kind="bands",need_payload=True,
            name="workspace_bands_octave_completed",
            note="1/1 octave band power bars, shared level colorbar (test fixture)")
        run("coherence_phase","multichannel",kind="coherence-phase",
            name="workspace_multichannel_coherence_completed",
            note="coherence 0..1 and phase (rad) from selected pair")
        run("io_pcm","time",kind="waveform",
            name="workspace_time_io_pcm_waveform_completed",
            note="six-channel PCM24 snapshot waveform (display extraction keeps peaks)")
        # page-level shot with live data + entry row
        vm.setCurrentPage("spectrum"); pump(0.4); vm.openFeatureEntry("psd"); pump(0.4)
        record("page_spectrum_entries_live", "psd", "spectrum", "spectrum",
               "page layout: 8-category icon entries + live PSD workspace")

    elif batch == "B":
        vm.setCurrentPage("advanced"); pump(0.4)
        from PySide6.QtQuick import QQuickItem
        adv = window.findChild(QQuickItem, "advancedToolsPage")
        if adv is not None:
            adv.setProperty("subTab", 2); pump(0.6)
        run("full_das","advanced",kind="das-map",need_image=True,
            name="workspace_directional_full_das_completed",
            note="manual DAS 2D power map (relative FS^2), local array angles")
        vm.setCurrentPage("directional"); pump(0.3)
        run("spatial_interface","directional",kind="capability",
            name="workspace_directional_spatial_interface",
            note="capability-only panel: manual DAS, no automatic DOA")
        if adv is not None:
            adv.setProperty("subTab", 3); pump(0.6)
        vm.setCurrentPage("advanced"); pump(0.3)
        vm.openFeatureEntry("room_decay"); pump(0.3)
        vm.featureConfirm("room_decay","stimulus","clap"); pump(0.3)
        vm.runFeature("room_decay")
        wait(lambda: vm.featureWorkspace.get("state") in ("completed","failed","canceled"), 40)
        pump(0.8)
        good, why = assert_workspace(("completed",), "room-decay", False, True)
        if good:
            record("workspace_room_decay_completed", "room_decay", "advanced", "room-decay",
                   "PL room decay after declared clap stimulus (experimental, not certified)")
        else:
            fail("room_decay", why)
        vm.setCurrentPage("events"); pump(0.3)
        vm.openFeatureEntry("event_trigger"); pump(0.3)
        vm.runFeature("event_trigger"); pump(2.0)
        good, why = assert_workspace(("running","accepted","queued"), "events", False, True)
        if good:
            record("workspace_events_monitor_running", "event_trigger", "events", "events",
                   "continuous event monitoring running (stop waits for canceled)")
        else:
            fail("event_trigger", why)
        vm.stopFeature("event_trigger")
        wait(lambda: vm.featureWorkspace.get("state") == "canceled", 25)

    elif batch == "C":
        run("levels_core","time",kind="level-bars",
            name="workspace_time_levels_completed",
            note="six-channel RMS/Peak/dBFS/crest/clip (invalid values shown as gaps)")
        vm.setCurrentPage("spectrum"); pump(0.3)
        vm.openFeatureEntry("spectrum_freeze"); pump(0.3)
        vm.runFeature("spectrum_freeze")
        ref_ok = wait(lambda: (vm.featureWorkspace.get("references") or {}).get("hasReference") is True, 40)
        vm.featureAction("spectrum_freeze","compare")
        wait(lambda: vm.featureWorkspace.get("state") == "completed"
             and (vm.featureWorkspace.get("chart") or {}).get("kind") == "ab-spectrum", 40)
        pump(0.8)
        good, why = assert_workspace(("completed",), "ab-spectrum", False, True) if ref_ok else (False, "no reference")
        if good:
            record("workspace_spectrum_freeze_ab_compare", "spectrum_freeze", "spectrum",
                   "ab-spectrum", "freeze reference A -> compare B: delta + threshold flags")
        else:
            fail("spectrum_freeze", why)
        vm.setCurrentPage("bands"); pump(0.3)
        vm.openFeatureEntry("noise_rating"); pump(0.3)
        vm.featureConfirm("noise_rating","referenceConfirmed",True); pump(0.3)
        vm.runFeature("noise_rating")
        wait(lambda: len([v for v in (vm.featureWorkspace.get("variants") or [])
                          if v.get("state")=="completed"]) >= 2, 40)
        pump(0.8)
        good, why = assert_workspace(("completed",), "noise-rating", False, True)
        if good:
            record("workspace_bands_noise_rating_nr_nc", "noise_rating", "bands", "noise-rating",
                   "NR + NC estimates with explicit nominal reference (not acoustic calibration)")
        else:
            fail("noise_rating", why)
        vm.setCurrentPage("spectrum"); pump(0.3)
        vm.openFeatureEntry("frequency_time_weighting"); pump(0.3)
        vm.runFeature("frequency_time_weighting")
        wait(lambda: len([v for v in (vm.featureWorkspace.get("variants") or [])
                          if v.get("state")=="completed"]) >= 2, 45)
        pump(0.8)
        good, why = assert_workspace(("completed",), "weighting", False, True)
        if good:
            record("workspace_bands_weighting_two_variants", "frequency_time_weighting",
                   "spectrum", "weighting",
                   "two independent PL runs: A/C/Z relative weighting vs Z unweighted FAST/SLOW/LeqFS")
        else:
            fail("weighting", why)

    elif batch == "D":
        vm.setCurrentPage("advanced"); pump(0.4)
        from PySide6.QtQuick import QQuickItem
        adv = window.findChild(QQuickItem, "advancedToolsPage")
        vm.openFeatureEntry("stipa_experimental"); pump(0.4)
        check_avail = vm.featureWorkspace.get("available")
        if not check_avail:
            fail("stipa_available", vm.featureWorkspace.get("disabledReason"))
        vm.runFeature("stipa_experimental")
        ref_ok = wait(lambda: (vm.featureWorkspace.get("references") or {}).get("hasReference") is True, 60)
        if not ref_ok:
            fail("stipa_reference", vm.featureWorkspace.get("state"))
        vm.featureConfirm("stipa_experimental","testSignalConfirmed",True); pump(0.4)
        vm.runFeature("stipa_experimental")
        wait(lambda: vm.featureWorkspace.get("state") in ("running","queued","accepted"), 20)
        progressed = wait(lambda: int(((vm.featureWorkspace.get("flow") or {}).get("stages") or {}).get("completed") or 0) >= 2, 60)
        pump(0.8)
        good, why = assert_workspace(("running",), "stipa", False, True)
        if good and progressed:
            record("workspace_room_stipa_stages_running", "stipa_experimental", "advanced",
                   "stipa", "experimental STIPA 101-stage graph running (stages progress, stop waits canceled)")
        else:
            fail("stipa_progress", why)
        vm.stopFeature("stipa_experimental")
        wait(lambda: vm.featureWorkspace.get("state") == "canceled", 30)

    elif batch == "E":
        run("csd","multichannel",kind="pair-spectra",
            name="workspace_multichannel_csd_completed",
            note="CSD/CSM selected pair: Sxx/Syy/CSD real-imag (units per schema)")
        run("third_octave","bands",kind="bands",
            name="workspace_bands_third_octave_completed",
            note="1/3 octave band power bars with real PL band centers")
        run("harmonic_ratio","periodic",kind="harmonic-bars",
            name="workspace_periodic_harmonic_bars_completed",
            note="harmonic band powers and THD from selected f0 (PL values)")
        run("waveform_like_cepstrum","periodic") if False else None
        run("cepstrum","periodic",kind="lag-series",
            name="workspace_periodic_cepstrum_completed",
            note="real cepstrum over quefrency (lag axis from schema)")

    elif batch == "P":
        run("psd","spectrum",kind="spectrum",
            name="dpi_spectrum_psd_completed",
            note="DPI variant: PSD chart layout/readability")
        run("stft","spectrum",kind="stft",need_image=True,
            name="dpi_spectrum_stft_2d_completed",
            note="DPI variant: STFT 2D heatmap + colorbar")
        run("octave","bands",kind="bands",
            name="dpi_bands_octave_completed",
            note="DPI variant: octave band bars")
        run("coherence_phase","multichannel",kind="coherence-phase",
            name="dpi_multichannel_coherence_completed",
            note="DPI variant: coherence/phase dual panel")

    else:
        raise SystemExit("unknown batch " + batch)

    manifest = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "batch": batch, "requestedSize": [width, height], "dpiScale": scale,
                "captureMethod": "real offscreen GUI against host test-feature-server (TCP 48120)",
                "assertions": ["connectionState=connected", "workspaceState as named",
                               "sourceKind=test-fixture", "chart payload present",
                               "fixture=non-live/NOT_TESTED"],
                "numericDSPVerified": False, "hardwareAccepted": False,
                "notes": ["Test fixture only; never pl-live; hardwareState=NOT_TESTED.",
                          "Feature parameters are fixed/hidden in the UI."],
                "failures": failures, "shots": shots}
    (OUT / f"capture_manifest_{batch}_{width}x{height}_dpi{int(scale*100)}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    vm.prepareExit(); pump(0.3); bridge.shutdown(); pump(0.2)
    print("BATCH_DONE", batch, "shots", len(shots), "failures", len(failures), flush=True)
    raise SystemExit(0 if not failures else 1)
finally:
    proc.terminate()
    try:
        o,e = proc.communicate(timeout=5)
        if e.strip(): print("SERVER-ERR", e[-300:])
    except Exception: pass