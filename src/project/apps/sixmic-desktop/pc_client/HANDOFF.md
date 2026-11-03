# PC feature extension handoff

This additive package supports all entries returned by `feature.list`; it does
not hardcode a subset of feature IDs, PL addresses or CPU algorithms. Existing
application/UI and frozen protocol sources are untouched.

## Existing backend integration

The actual DeviceSession lives at
`apps/sixmic-desktop/backend/sixmic_backend/session.py`, not
`session/device_session.py`. Put `deployment/echo_feature_closure_20261025` on
the Python import path alongside `apps/sixmic-desktop/backend`.

```python
from pc_client import FeatureClient
features = FeatureClient(existing_device_session)
catalog = features.list_features()
accepted = features.start_feature(catalog['features'][0]['featureId'], {})
job = features.get_feature(accepted['jobId'])
# Poll only as required until state says the result is available.
result = features.get_feature_result(accepted['jobId'])
metadata = result.to_dict()  # FeatureResult + DataRef, never a guessed address
raw_bytes = existing_device_session.data_store.read_slice(
    result.data_ref['handleId'], 0, result.data_ref['count'])
features.release_result(result)
```

Control writes claim through DeviceSession.claim_control when needed and use
the same live token that its existing renewal thread renews. A changed login
session invalidates the prior token. Start/stop are never retried or replayed
implicitly. Reads require the existing authenticated session, not a lease.

`transport.py` is the only extension seam: frozen `build_request` rejects new
operations. For real ControlClient instances it constructs only the five
explicitly allowed feature envelopes and uses the existing socket, ID source,
pending table, reader validation, errors and response timeout. No global
whitelist patch or second connection is made. It deliberately accesses private
ControlClient fields; maintain this one file if ControlClient internals change.
Alternate/fake controls use their public `request(op,args)` method.

## Frontend Agent integration

Minimal integration change for the existing frontend Agent: instantiate
`pc_client.qt_bridge.FeatureBackendBridge` where `BackendBridge` is currently
instantiated, keeping the same QML context name and constructor arguments.
Existing bridge methods/signals are inherited. No GUI redesign is required.
The new slots all return the ordinary UI request ID immediately and run on the
existing dedicated serial worker:

| Slot | Parameters | Existing completion envelope result |
| --- | --- | --- |
| listFeatures | none | `{features:[metadata], version}` |
| startFeature | featureId, paramsJson (JSON object string) | accepted `{jobId}` |
| stopFeature | jobId | server stop response |
| getFeature | jobId | job state/progress/error/source metadata |
| getFeatureResult | jobId | typed FeatureResult metadata and `dataRef` |
| releaseFeatureResult | handleId | `{released:bool}` |

Use existing completion/error signals and match `requestId`. BackendBridge's
completion outer `status` is `ok`; the nested result retains server
`responseStatus` (`accepted` for start). Keep `generation` and `sourceFrame` as
decimal strings. `dataRef.elementType` is `uint32`, byte encoding is little
endian. Schema fields/axes/units/validity describe interpretation; no DSP or
float reinterpretation is performed here. Consumers can use the existing
`readBuffer` slot for bounded local slices and release the handle when done.

The result fetch uses <=1024 words per request, checks every page's identity,
configuration, schema and provenance, rejects stalled/overlapping/inconsistent
pages, validates uint32 values and preserves their exact bits. It stores the
complete result in existing capacity-bounded DataStore. The client result
limit defaults to 16 Miwords (64 MiB); DataStore can impose a smaller limit.
`pl-live` and `test-fixture` are retained exactly, never relabeled. A running job
without a readable result should return a server not-ready error; client callers
should use `getFeature` to determine when to fetch.

## Short verification

Run from repo root:

```text
python deployment/echo_feature_closure_20261025/pc_client/test_client.py
```

Eight isolated tests cover lease reuse/reclaim, catalog/start/stop, exact bits
and >2^53/uint64 counters, multi-page transfer, unstable snapshots, invalid or
stalled pages, capacity rejection, fixture provenance and the real
ControlClient extension envelope with a fake send function. No old test suite,
physical-board verification, networking, CPU DSP or GUI exercise is included.

Hardware callable acceptance still requires PS `feature.*` support and the
corresponding PL kernel path. These PC tests do not establish those conditions.
