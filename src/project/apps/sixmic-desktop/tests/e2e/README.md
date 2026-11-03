# Feature-wiring E2E suite (host fixture gateway)

SIMULATED / test-fixture: everything in this directory talks to
deployment/echo_feature_closure_20261025/ps/build/host/test-feature-server.exe,
a deterministic host fixture gateway. It is not a PL bitstream, not the board,
not acoustic data. Every artifact is marked sourceKind=test-fixture,
numericDSPVerified=false, hardwareState=NOT_TESTED.

## What is real

* backend/sixmic_backend: DeviceSession, ControlClient, DataStore, frozen
  protocol validation.
* pc_client.FeatureClient: the shipping client used by the product UI layer
  (with its 64 req/s request pacing; Lead change 2026-10-26).
* TCP JSON-lines transport on an OS-assigned loopback port, real fixture process.

## What is not established

* No PL/PS program execution, no board deploy, no acoustic accuracy, no
  numeric acceptance. matrix column hardwareState is always NOT_TESTED.

## Run

    apps/sixmic-desktop/.venv/Scripts/python.exe apps/sixmic-desktop/tests/e2e/run_e2e.py

or plain pytest:

    apps/sixmic-desktop/.venv/Scripts/python.exe -m pytest apps/sixmic-desktop/tests/e2e -q

A fresh fixture process is started per test (the fixture exits after 60 s of
wall clock). Evidence JSON is written to tests/e2e/evidence/; run_e2e.py also
writes evidence/pytest.log.

## Coverage

| Module | Establishes |
|---|---|
| test_capability_state.py | unit: bool + string capability encodings both parse (Lead dto.capability_state) |
| test_client_pacing.py | unit: 64 req/s/64 burst token bucket arithmetic |
| test_gateway_capability.py | live: capability bool normalization, featureApi enabled, fixture markers |
| test_catalog_pagination.py | 51 unique features, cursor 8/16/1 paging, invalid limits |
| test_feature_lifecycle.py | p0/p1/p2 representative start->get->completed->result, events monitor; zoom_fft completes after registry fix |
| test_pagination_boundaries.py | 1024-word page cap, exact reassembly, invalid pages, bad tokens |
| test_scheduling.py | exclusive busy, stop->canceled, 8-slot recycle |
| test_large_results.py | room_decay 48032 words, io_pcm 720000 words / 704 pages / pacing timing, unpaced negative proof |
| test_reference_flows.py | freeze compare, relative limit, insulation measure, STIPA 2 stages->cancel, confirmation gates |
| test_reconnect_identity.py | new session/claim after reconnect, job identity, decimal-string counters |
| test_all_feature_starts.py | all 51 launch kinds on fresh fixtures -> evidence/feature_start_matrix.json |

## zoom_fft registry fix (2026-10-26)

The candidate device registry's acquisitionPreparationPlan now provides
inputWords=4159 / inputWordOffset=1069056 (32-bit words in the PL analysis
arena). The host fixture completes start -> completed with capturedSamples=4159
and a 4096-word tensor result (evidence/zoom_fft_registry_fix.json), and all
51 features pass the start survey (deviceGap=0). The PC does not recompute
Zoom FFT and does not change the wire protocol.

Boundary: physicalBoardTested=false, hardwareAccepted=false,
numericDSPVerified=false, hardwareState=NOT_TESTED. A host-fixture PASS is not a
board or acoustic acceptance.
