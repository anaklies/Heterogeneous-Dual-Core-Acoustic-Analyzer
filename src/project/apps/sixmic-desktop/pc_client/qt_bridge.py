"""Additive Qt subclass; all device work uses BackendBridge's serial worker."""
import json

from sixmic_backend.errors import BackendError
from sixmic_backend.qt.adapter import BackendBridge, Slot
from .client import FeatureClient


class FeatureBackendBridge(BackendBridge):
    def _features(self):
        session = self._session_or_none()
        if session is None:
            raise BackendError("not_connected", {"reason": "feature-session"})
        client = getattr(self, "_feature_client", None)
        if client is None or client.session is not session:
            client = self._feature_client = FeatureClient(session)
        return client

    @Slot(result=str)
    def listFeatures(self):
        return self._submit("listFeatures", lambda: self._features().list_features())

    @Slot(str, str, result=str)
    def startFeature(self, featureId, paramsJson="{}"):
        def run():
            try:
                params = json.loads(paramsJson)
            except (ValueError, TypeError) as exc:
                raise BackendError("bad_args", {"field": "paramsJson"}) from exc
            if not isinstance(params, dict):
                raise BackendError("bad_args", {"field": "paramsJson"})
            return self._features().start_feature(featureId, params)
        return self._submit("startFeature", run)

    @Slot(str, result=str)
    def stopFeature(self, jobId):
        return self._submit("stopFeature", lambda: self._features().stop_feature(jobId))

    @Slot(str, result=str)
    def getFeature(self, jobId):
        return self._submit("getFeature", lambda: self._features().get_feature(jobId))

    @Slot(str, result=str)
    def getFeatureResult(self, jobId):
        return self._submit("getFeatureResult", lambda: self._features().get_feature_result(jobId).to_dict())

    @Slot(str, result=str)
    def releaseFeatureResult(self, handleId):
        return self._submit("releaseFeatureResult", lambda: {
            "released": self._features().session.data_store.release(handleId)})

    @Slot(result=str)
    def featureApiInfo(self):
        """Gateway-level echo-features-1 capability (read from the live hello).

        The frozen device capability DTO only models per-device states, so the
        gateway featureApi block is exposed verbatim as JSON here.  Missing
        block means an old gateway: the UI must ask for a device software
        update instead of calling the new operations.
        """
        payload = {"connected": False, "enabled": False, "version": "",
                   "featureCount": 0, "maxResultWordsPerPage": 1024,
                   "catalogPageSize": 8, "reason": "not-connected"}
        session = self._session_or_none()
        if session is None:
            return json.dumps(payload, ensure_ascii=False)
        hello = getattr(session, "hello", None) or {}
        gateway = ((hello.get("capabilities") or {}).get("gateway") or {})
        api = gateway.get("featureApi")
        if not isinstance(api, dict):
            payload.update(connected=True, reason="feature-api-missing")
            return json.dumps(payload, ensure_ascii=False)
        payload.update(connected=True, enabled=bool(api.get("enabled")),
                       version=str(api.get("version") or ""),
                       featureCount=int(api.get("featureCount") or 0),
                       maxResultWordsPerPage=int(api.get("maxResultWordsPerPage") or 1024),
                       catalogPageSize=int(api.get("catalogPageSize") or 8),
                       reason="" if api.get("enabled") else "feature-api-disabled")
        return json.dumps(payload, ensure_ascii=False)
