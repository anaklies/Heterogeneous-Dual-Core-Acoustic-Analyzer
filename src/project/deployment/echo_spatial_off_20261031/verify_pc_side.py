
import json, sys, time
from pathlib import Path
ROOT = Path(r"C:\Users\sunxi\Desktop\sixmic3D")
sys.path.insert(0, str(ROOT / "apps/sixmic-desktop/backend"))
sys.path.insert(0, str(ROOT / "apps/sixmic-desktop"))
from sixmic_backend.transport.control_client import ControlClient
from sixmic_backend.data.data_store import DataStore
from sixmic_backend.errors import BackendError
from pc_client.client import FeatureClient

spatial = ["spatial_interface","directed_das","full_das","band_das","spatial_grid","spatial_peaks"]
out = {"board": "192.168.77.2:48120", "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
ctl = ControlClient("192.168.77.2", 48120, auto_reconnect=False)
hello = ctl.connect()
out["hello"] = {k: hello.get(k) for k in ("protocol","protocolVersion","sessionId","deviceId","connectionEpoch") if k in hello}
class Session:
    control = ctl
    data_store = DataStore()
    _control_token = None
    def claim_control(self):
        r = ctl.request("control.claim", {"leaseSeconds": 60})
        self._control_token = r.get("controlToken") or r.get("token")
        return r
s = Session()
fc = FeatureClient(s)
listing = fc.list_features()
ids = [f.get("featureId") for f in listing.get("features") or []]
out["featureList"] = {"version": listing.get("version"), "total": listing.get("total"), "count": len(ids),
                      "hasSpatial": [x for x in spatial if x in ids], "first": ids[:5], "last": ids[-3:]}
try:
    claim = s.claim_control()
    out["controlClaim"] = {"ok": True, "tokenPresent": bool(s._control_token)}
except BackendError as exc:
    out["controlClaim"] = {"ok": False, "code": exc.code, "detail": str(exc)[:200]}
rejects = {}
for fid in ("spatial_interface", "full_das"):
    try:
        r = fc.start_feature(fid)
        rejects[fid] = {"rejected": False, "response": r}
    except BackendError as exc:
        rejects[fid] = {"rejected": True, "code": exc.code, "message": str(exc)[:300]}
out["spatialStartRejections"] = rejects
out["pass"] = (out["featureList"]["total"] == 45 and out["featureList"]["count"] == 45
               and not out["featureList"]["hasSpatial"]
               and all(v["rejected"] for v in rejects.values()))
(ROOT / "deployment/echo_spatial_off_20261031/POST_DEPLOY_PC.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(out, indent=2, ensure_ascii=False))
ctl.close()
