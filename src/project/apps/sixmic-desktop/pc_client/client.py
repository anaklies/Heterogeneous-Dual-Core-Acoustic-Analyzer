"""DeviceSession-backed feature client. Raw bits only; no CPU DSP."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import struct
import time
import threading
from typing import Any

from sixmic_backend.errors import BackendError
from sixmic_backend.protocol.control import parse_u64, u64
from .transport import request


def _bad(reason):
    raise BackendError("schema_mismatch", {"reason": reason})


def _integer(value, field, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        _bad(field)
    return value


class _TokenBucket:
    """Local request pacer matching the documented gateway budget.

    The gateway documents at most 64 requests/second with a small burst
    allowance.  Paging a 720000-word PCM result needs 704 result requests; an
    unpaced client trips the gateway limiter, whose throttled responses are
    dropped and end as request timeouts.  This bucket spends the documented
    budget locally: burst up to the capacity, then refill at the rate.
    """

    def __init__(self, rate: float = 64.0, capacity: int = 64, *,
                 clock=time.monotonic, sleep=time.sleep) -> None:
        self.rate = float(rate)
        self.capacity = float(capacity)
        self._tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self.waited_seconds = 0.0
        self.requests = 0

    def acquire(self) -> float:
        if self.rate <= 0:
            self.requests += 1
            return 0.0
        now = self._clock()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last = now
        waited = 0.0
        if self._tokens >= 1.0:
            self._tokens -= 1.0
        else:
            waited = (1.0 - self._tokens) / self.rate
            self._sleep(waited)
            self._tokens = 0.0
            self._last = self._clock()
        self.requests += 1
        self.waited_seconds += waited
        return waited


@dataclass(frozen=True)
class FeatureResult:
    job_id: str
    feature_id: str
    state: str
    source_kind: str
    configuration: dict[str, Any]
    schema: dict[str, Any]
    data_ref: dict[str, Any]

    def to_dict(self):
        return deepcopy({"jobId": self.job_id, "featureId": self.feature_id,
                         "state": self.state, "sourceKind": self.source_kind,
                         "configuration": self.configuration, "schema": self.schema,
                         "totalWords": self.data_ref["count"], "dataRef": self.data_ref})


class FeatureClient:
    def __init__(self, session, *, max_result_words=16 * 1024 * 1024,
                 request_rate=48.0, request_burst=48):
        self.session = session
        self.max_result_words = max_result_words
        self._lease_session = getattr(session.control, "session_id", None)
        self._pacing_lock=threading.Lock()
        self._feature_modes={};self._readonly_jobs={};self._start_busy_retries=0
        # PC-side pacing is a protocol requirement, not an optimisation: the
        # gateway drops over-rate requests and the frozen transport treats the
        # silence as a timeout.  Tests may pass request_rate=0 to disable it.
        self._limiter = _TokenBucket(rate=request_rate,
                                     capacity=max(1, int(request_burst)))

    def _request(self, op, args):
        control = self.session.control
        if control is None:
            raise BackendError("not_connected", {"reason": op})
        with self._pacing_lock:self._limiter.acquire()
        return request(control, op, args)

    def _token(self):
        # DeviceSession owns renewal. Its current reconnect callback does not
        # clear tokens, so invalidate an old lease when the login changes.
        current_session = getattr(self.session.control, "session_id", None)
        if current_session != self._lease_session:
            self.session._control_token = None
            self._lease_session = current_session
        token = self.session._control_token
        if not token:
            self.session.claim_control()
            token = self.session._control_token
        if not token:
            raise BackendError("control_not_held", {"reason": "feature-control"})
        return token

    def list_features(self):
        cursor, result, collected, seen = 0, None, [], set()
        while cursor is not None:
            if cursor in seen:
                _bad("feature-catalog-pagination")
            seen.add(cursor)
            page = self._request("feature.list", {"cursor": cursor, "limit": 8})
            if not isinstance(page.get("features"), list) or "version" not in page:
                _bad("feature-catalog")
            if result is None:
                result = deepcopy(page)
            elif page["version"] != result["version"]:
                _bad("feature-catalog-version")
            collected.extend(page["features"])
            cursor = page.get("nextCursor")
        result["features"] = collected
        self._feature_modes={row.get('featureId'):row.get('mode') for row in collected}
        result["nextCursor"] = None
        return result

    def start_feature(self, feature_id, params=None):
        if not isinstance(feature_id, str) or not feature_id or (params is not None and not isinstance(params, dict)):
            raise BackendError("bad_args", {"field": "featureId/params"})
        values=deepcopy(params or {})
        readonly=self._feature_modes.get(feature_id) in {'p0','p1'} and not(feature_id=='io_pcm' and values.get('samples'))
        if self._feature_modes.get(feature_id)=='p1' and (values.get('autoChannel') or int(values.get('channel',0))!=0):readonly=False
        args={"featureId":feature_id,"params":values}
        if not readonly:args['controlToken']=self._token()
        # A busy response explicitly rejects admission: no job was started.
        # Retry that rejection briefly, never timeout/disconnect/unknown outcome.
        for attempt in range(6):
            try:
                result = self._request("feature.start", args)
                break
            except BackendError as exc:
                if exc.code != "busy" or attempt == 5:
                    raise
                self._start_busy_retries += 1
                time.sleep(.05 * (attempt + 1))
        if not isinstance(result.get("jobId"), str) or not result["jobId"]:
            _bad("feature-job-id")
        self._readonly_jobs[result['jobId']]=readonly
        if len(self._readonly_jobs)>128:self._readonly_jobs.pop(next(iter(self._readonly_jobs)))
        return result

    def stop_feature(self, job_id):
        args={'jobId':job_id}
        if not self._readonly_jobs.get(job_id,False):args['controlToken']=self._token()
        return self._request("feature.stop",args)

    def get_feature(self, job_id):
        result = self._request("feature.get", {"jobId": job_id})
        if result.get("jobId") != job_id:
            _bad("feature-job-id")
        return result

    def get_feature_result(self, job_id):
        """Fetch one stable result into DataStore; caller owns/releases dataRef."""
        offset, snapshot, data = 0, None, bytearray()
        api=((getattr(self.session,'hello',None) or {}).get('capabilities',{}).get('gateway',{}).get('featureApi',{}))
        page_words=max(1,min(4096,int(api.get('maxResultWordsPerPage',1024))))
        while True:
            page = self._request("feature.result", {"jobId": job_id,
                                 "offsetWords": offset, "maxWords": page_words})
            page_offset = _integer(page.get("offsetWords"), "offsetWords", self.max_result_words)
            if page.get("jobId") != job_id or page_offset != offset:
                _bad("feature-result-position")
            total = _integer(page.get("totalWords"), "totalWords", self.max_result_words)
            words = page.get("words")
            if not isinstance(words, list) or len(words) > page_words or offset + len(words) > total:
                _bad("feature-result-length")
            for word in words:
                _integer(word, "uint32-word", 0xffffffff)
            if page.get("sourceKind") not in {"pl-live", "test-fixture"}:
                _bad("feature-result-source")
            configuration, schema = page.get("configuration"), page.get("schema")
            if not isinstance(configuration, dict) or not all(
                    key in configuration for key in ("session", "config", "generation", "sourceFrame")):
                _bad("feature-result-configuration")
            if not isinstance(schema, dict) or not all(
                    key in schema for key in ("kind", "fields", "axes", "units", "validity")):
                _bad("feature-result-schema")
            # Counters cross the QML/JSON boundary as decimal strings. No
            # float conversion is permitted, including values above 2**53.
            configuration = deepcopy(configuration)
            for key in ("generation", "sourceFrame"):
                configuration[key] = u64(parse_u64(configuration[key], key))
            page = dict(page, configuration=configuration)
            identity = {key: deepcopy(page.get(key)) for key in
                        ("jobId", "featureId", "state", "sourceKind", "configuration", "schema", "totalWords")}
            if not isinstance(identity["featureId"], str) or not isinstance(identity["state"], str):
                _bad("feature-result-identity")
            if snapshot is None:
                snapshot = identity
                available = self.session.data_store.budget.capacity_bytes - self.session.data_store.budget.used
                if total * 4 > available:
                    raise BackendError("storage_full", {"reason": "feature-result-capacity"})
            elif identity != snapshot:
                _bad("feature-result-changed-during-pagination")
            data.extend(struct.pack("<" + "I" * len(words), *words))
            offset += len(words)
            more = page.get("more")
            if not isinstance(more, bool) or more != (offset < total) or (more and not words):
                _bad("feature-result-pagination")
            if not more:
                break
        handle_id = self.session.data_store.put(bytes(data), "uint32", display_only=False,
                                                source_kind=snapshot["sourceKind"])
        return FeatureResult(job_id, snapshot["featureId"], snapshot["state"], snapshot["sourceKind"],
                             snapshot["configuration"], snapshot["schema"],
                             self.session.data_store.get(handle_id).to_ref())

    def release_result(self, result):
        return self.session.data_store.release(result.data_ref["handleId"])
