"""Feature envelopes on the existing authenticated ControlClient connection.

The frozen protocol builder rejects extension operations. This narrowly scoped
adapter reuses its socket, request IDs, pending response table and reader; it
does not create another login, mutate operation allowlists, or replay commands.
"""
from sixmic_backend.constants import PROTOCOL_NAME, PROTOCOL_VERSION
from sixmic_backend.errors import BackendError
from sixmic_backend.protocol.jsonline import encode_line
from sixmic_backend.transport.control_client import ControlClient, _Pending

FEATURE_OPS = frozenset({"feature.list", "feature.start", "feature.stop",
                         "feature.get", "feature.result"})


def request(control, op, args):
    if op not in FEATURE_OPS:
        raise BackendError("unknown_op", {"op": op})
    if not isinstance(control, ControlClient):
        # Explicit fake/alternate transport implementing the normal request API.
        return control.request(op, args)
    if not control._connected.is_set() or not control.session_id:
        raise BackendError("not_connected", {"reason": "feature-control"})
    request_id = control._next_request_id()
    payload = {"protocol": PROTOCOL_NAME, "version": PROTOCOL_VERSION,
               "requestId": request_id, "sessionId": control.session_id,
               "op": op, "args": dict(args)}
    pending = _Pending()
    with control._lock:
        control._pending[request_id] = pending
    try:
        try:
            control._send(encode_line(payload))
        except OSError as exc:
            raise BackendError("io_error", {"reason": "feature-send"}) from exc
        if not pending.event.wait(control.request_timeout):
            raise BackendError("timeout", {"op": op, "requestId": request_id})
        if pending.error is not None:
            raise pending.error
        response = pending.payload or {}
        if response.get("status") == "error":
            error = response.get("error") or {}
            raise BackendError(str(error.get("code", "internal_error")),
                               dict(error.get("detail") or {}),
                               message_key=error.get("messageKey"),
                               retryable=bool(error.get("retryable", False)))
        result = dict(response.get("result") or {})
        result.update(requestId=request_id, responseStatus=response.get("status"))
        return result
    finally:
        with control._lock:
            control._pending.pop(request_id, None)
