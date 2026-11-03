"""All-51 real-stack start/result survey (fresh fixture per feature).

Each of the 51 catalog entries is started exactly once with the fixed hidden
launch parameters from ui/config/feature_view_spec.json, through the real
application stack (DeviceSession + stock FeatureClient) against a *fresh*
host fixture process.  The resulting evidence file drives the 51-row wiring
matrix (docs/frontend/51_FEATURE_WIRING_MATRIX.*).

SIMULATED / test-fixture: this proves PC wiring + protocol transport only.
hardwareState stays NOT_TESTED.  The candidate registry now provides the
zoom_fft inputWords/inputWordOffset fields (2026-10-26 fix), so all 51 starts
are expected to reach completed on the host fixture; this is still not a board
or acoustic acceptance.
"""
from __future__ import annotations

import json
import time

import pytest

import harness
from sixmic_backend.errors import BackendError

pytestmark = pytest.mark.e2e

SPEC = harness.load_spec()["features"]
TERMINAL = ("completed", "failed", "canceled")


def _wait(stack, job_id, timeout=20.0):
    return stack.wait(job_id, timeout=timeout)


def _run_feature(label, feature_id, entry):
    """Start one feature on a fresh fixture; return its evidence record."""
    record = {
        "featureId": feature_id,
        "page": entry["page"],
        "group": entry["group"],
        "tier": entry["tier"],
        "mode": entry["mode"],
        "launchKind": (entry.get("launch") or {}).get("kind"),
        "launchParams": None,
        "outcome": "failed",
        "states": {},
        "jobIds": [],
        "totalWords": None,
        "schemaKind": None,
        "sourceKind": None,
        "error": None,
        "elapsedSeconds": None,
    }
    started = time.monotonic()
    stack = None
    try:
        stack = harness.AppStack(label=f"survey-{label}")
        record["fixtureControlPort"] = stack.ready["controlPort"]
        launch = entry.get("launch") or {}
        kind = launch.get("kind")
        client = stack.client
        if kind in ("reference_compare", "reference_measure"):
            reference_params = dict(launch.get("referenceParams") or {})
            second_key = "compareParams" if kind == "reference_compare" else "measureParams"
            second_params = dict(launch.get(second_key) or {})
            record["launchParams"] = {"referenceParams": reference_params,
                                      second_key: second_params}
            ref = stack.start(feature_id, reference_params)
            ref_done = _wait(stack, ref["jobId"])
            record["jobIds"].append(ref["jobId"])
            record["states"]["reference"] = ref_done["state"]
            if ref_done["state"] != "completed":
                record["error"] = {"stage": "reference", "state": ref_done["state"],
                                   "detail": ref_done.get("error")}
                return record
            second = stack.start(feature_id,
                                 dict(second_params, referenceJobId=ref["jobId"]))
            second_done = _wait(stack, second["jobId"])
            record["jobIds"].append(second["jobId"])
            record["states"]["result"] = second_done["state"]
            if second_done["state"] != "completed":
                record["error"] = {"stage": "second", "state": second_done["state"],
                                   "detail": second_done.get("error")}
                return record
            page = stack.result_page(second["jobId"], 0, 1024)
        elif kind == "staged_stipa":
            reference_params = dict(launch.get("referenceParams") or {})
            record["launchParams"] = {"referenceParams": reference_params,
                                      "stipaParams": dict(launch.get("stipaParams") or {})}
            ref = stack.start("io_pcm", reference_params)
            ref_done = _wait(stack, ref["jobId"])
            record["jobIds"].append(ref["jobId"])
            record["states"]["reference"] = ref_done["state"]
            if ref_done["state"] != "completed":
                record["error"] = {"stage": "reference", "state": ref_done["state"]}
                return record
            staged = stack.start(feature_id,
                                 dict(launch.get("stipaParams") or {},
                                      referenceJobId=ref["jobId"]))
            record["jobIds"].append(staged["jobId"])
            deadline = time.monotonic() + 20
            progress = stack.get(staged["jobId"])
            while (time.monotonic() < deadline
                   and progress["state"] not in TERMINAL
                   and progress["progress"]["completedStages"] < 2):
                time.sleep(0.005)
                progress = stack.get(staged["jobId"])
            record["states"]["running"] = progress["state"]
            record["completedStages"] = progress["progress"]["completedStages"]
            if progress["state"] in TERMINAL:
                record["states"]["final"] = progress["state"]
            else:
                stack.stop(staged["jobId"])
                record["states"]["final"] = _wait(stack, staged["jobId"])["state"]
            final = record["states"]["final"]
            record["outcome"] = "passed" if (
                record["completedStages"] >= 2
                and final in ("canceled", "completed")) else "failed"
            return record
        elif kind == "monitor":
            params = dict(launch.get("params") or {})
            record["launchParams"] = params
            accepted = stack.start(feature_id, params)
            record["jobIds"].append(accepted["jobId"])
            running = stack.get(accepted["jobId"])
            record["states"]["running"] = running["state"]
            stack.stop(accepted["jobId"])
            final = _wait(stack, accepted["jobId"])
            record["states"]["final"] = final["state"]
            if running["state"] == "running" and final["state"] == "canceled":
                record["outcome"] = "passed"
            else:
                record["error"] = {"running": running["state"], "final": final["state"]}
            return record
        elif kind == "dual_variant":
            states = {}
            for run in launch.get("runs") or []:
                params = dict(run.get("params") or {})
                accepted = stack.start(feature_id, params)
                record["jobIds"].append(accepted["jobId"])
                done = _wait(stack, accepted["jobId"])
                states[str(run.get("id"))] = done["state"]
                if done["state"] != "completed":
                    record["error"] = {"variant": run.get("id"),
                                       "state": done["state"],
                                       "detail": done.get("error")}
                    record["states"] = states
                    return record
            record["launchParams"] = [dict(run.get("params") or {})
                                      for run in launch.get("runs") or []]
            record["states"] = states
            page = stack.result_page(record["jobIds"][-1], 0, 1024)
        elif kind == "room_stimulus":
            params = {"stimulus": "clap"}
            record["launchParams"] = params
            accepted = stack.start(feature_id, params)
            record["jobIds"].append(accepted["jobId"])
            done = _wait(stack, accepted["jobId"])
            record["states"]["result"] = done["state"]
            if done["state"] != "completed":
                record["error"] = {"state": done["state"], "detail": done.get("error")}
                return record
            page = stack.result_page(accepted["jobId"], 0, 1024)
        else:  # single
            params = dict(launch.get("params") or {})
            record["launchParams"] = params
            accepted = stack.start(feature_id, params)
            record["jobIds"].append(accepted["jobId"])
            done = _wait(stack, accepted["jobId"])
            record["states"]["result"] = done["state"]
            if done["state"] != "completed":
                record["error"] = {"state": done["state"], "detail": done.get("error")}
                return record
            page = stack.result_page(accepted["jobId"], 0, 1024)
        record["totalWords"] = page["totalWords"]
        record["schemaKind"] = page["schema"]["kind"]
        record["sourceKind"] = page["sourceKind"]
        record["outcome"] = "passed"
        return record
    except BackendError as exc:
        record["error"] = {"code": exc.code, "detail": exc.detail,
                           "stage": "start_or_poll"}
        known_gap = (entry.get("devicePath") or {}).get("knownGap")
        if known_gap and exc.code == "bad_args":
            record["outcome"] = "device-gap"
            record["knownGap"] = known_gap
        else:
            record["outcome"] = "failed"
        return record
    except Exception as exc:  # noqa: BLE001 - recorded, then asserted by the test
        record["error"] = {"exception": repr(exc)[:400], "stage": "harness"}
        return record
    finally:
        record["elapsedSeconds"] = round(time.monotonic() - started, 3)
        if stack is not None:
            try:
                stack.close()
            except Exception as exc:  # noqa: BLE001
                record.setdefault("closeError", repr(exc)[:200])


def test_all_51_features_start_on_host_fixture():
    spec = harness.load_spec()
    features = spec["features"]
    order = []
    for page in spec["pages"].values():
        for group in page["groups"]:
            order.extend(group["features"])
    assert len(order) == len(set(order)) == 51
    assert set(order) == set(features)

    results = []
    started = time.monotonic()
    for label, feature_id in enumerate(order):
        record = _run_feature(label, feature_id, features[feature_id])
        results.append(record)
        print("SURVEY", feature_id, record["outcome"],
              record["states"], record.get("totalWords"), flush=True)

    passed = [row for row in results if row["outcome"] == "passed"]
    device_gaps = [row for row in results if row["outcome"] == "device-gap"]
    failures = [row for row in results if row["outcome"] == "failed"]
    summary = {
        "total": len(results),
        "lifecyclePassed": len(passed),
        "deviceGaps": len(device_gaps),
        "failures": len(failures),
        "deviceGapFeatureIds": [row["featureId"] for row in device_gaps],
        "failedFeatureIds": [row["featureId"] for row in failures],
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "fixtureProcessStarts": len(harness.GATEWAY_STARTS),
        "hardwareState": "NOT_TESTED",
        "numericDSPVerified": False,
        "sourceKind": "test-fixture",
        "banner": harness.SIMULATED_BANNER,
    }
    harness.record_artifact("feature_start_matrix", {
        "summary": summary,
        "features": results,
        "specSha256": harness.file_sha256(harness.SPEC_JSON),
        "registrySha256": harness.file_sha256(harness.REGISTRY_JSON),
        "fixtureExeSha256": harness.file_sha256(harness.SERVER_EXE),
    })
    print("SURVEY_SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)

    assert not failures, f"unexpected failures: {json.dumps(failures, ensure_ascii=False)}"
    assert not device_gaps, (
        "zoom_fft registry fix is in place; no device-gap row expected; "
        f"got {[row['featureId'] for row in device_gaps]}")
    assert len(passed) == 51
