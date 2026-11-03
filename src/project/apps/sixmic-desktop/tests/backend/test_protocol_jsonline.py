"""Control-channel JSON Lines rules from PROTOCOL.md section 2.1/2.8."""
from __future__ import annotations

import json

import pytest

from sixmic_backend.constants import MAX_LINE_BYTES, PROTOCOL_NAME, PROTOCOL_VERSION
from sixmic_backend.errors import BackendError
from sixmic_backend.protocol.control import (
    build_event, build_request, build_response, parse_u64, u64,
    validate_event, validate_request, validate_response,
)
from sixmic_backend.protocol.jsonline import LineDecoder, decode_line, encode_line


def test_partial_and_sticky_packets():
    decoder = LineDecoder()
    assert decoder.feed(b'{"a":1}\n{"b"') == [{"a": 1}]
    assert decoder.feed(b'\x3a2}\n') == [{"b": 2}]  # completes the partial line
    assert decoder.feed(b'{"c":3}\n{"d":4') == [{"c": 3}]
    assert decoder.feed(b"}\n") == [{"d": 4}]
    assert decoder.empty_lines == 0


def test_empty_lines_ignored():
    decoder = LineDecoder()
    assert decoder.feed(b"\n\n") == []
    assert decoder.empty_lines == 2


def test_utf8_multibyte_split_across_reads():
    payload = json.dumps({"text": "声学"}, ensure_ascii=False).encode() + b"\n"
    decoder = LineDecoder()
    assert decoder.feed(payload[:5]) == []
    decoded = decoder.feed(payload[5:])
    assert decoded[0]["text"] == "声学"


@pytest.mark.parametrize("raw", [
    b'{"a":1,"a":2}',
    b'{"a": NaN}',
    b'{"a": Infinity}',
    b'[1,2,3]',
    b'"string"',
    b'{"a":1}\r',
])
def test_invalid_json_rejected(raw):
    with pytest.raises(BackendError) as info:
        decode_line(raw)
    assert info.value.code in ("bad_json", "bad_utf8")


def test_invalid_utf8_rejected():
    with pytest.raises(BackendError) as info:
        decode_line(b"\xff\xfe")
    assert info.value.code == "bad_utf8"


def test_oversize_line_rejected():
    decoder = LineDecoder()
    with pytest.raises(BackendError) as info:
        decoder.feed(b"x" * (MAX_LINE_BYTES + 1))
    assert info.value.code == "line_too_long"


def test_encode_oversize_rejected():
    with pytest.raises(BackendError) as info:
        encode_line({"big": "y" * MAX_LINE_BYTES})
    assert info.value.code == "line_too_long"


def test_depth_limit():
    deep = json.loads("[" * 40 + "0" + "]" * 40)
    with pytest.raises(BackendError) as info:
        decode_line(json.dumps({"deep": deep}).encode())
    assert info.value.code == "bad_json"


def test_request_validation():
    request = build_request("status.get", "c-1", "sess-1", {})
    request_id, session, op, args = validate_request(request)
    assert (request_id, session, op, args) == ("c-1", "sess-1", "status.get", {})
    with pytest.raises(BackendError) as info:
        validate_request({**request, "protocol": "old-protocol"})
    assert info.value.code == "protocol_mismatch"
    with pytest.raises(BackendError) as info:
        validate_request({**request, "version": 2})
    assert info.value.code == "unsupported_version"
    with pytest.raises(BackendError) as info:
        validate_request({**request, "op": "shell.exec"})
    assert info.value.code == "unknown_op"
    hello = build_request("hello", "c-2", None, {})
    assert validate_request(hello)[2] == "hello"


def test_response_and_event_validation():
    response = build_response("c-1", "ok", {"x": 1})
    assert validate_response(response, "c-1")["status"] == "ok"
    error = build_response("c-2", "error", error={"code": "not_ready",
                                                  "messageKey": "errors.not_ready",
                                                  "retryable": False})
    assert validate_response(error, "c-2")["status"] == "error"
    with pytest.raises(BackendError):
        validate_response(response, "other")
    event = build_event("jobUpdated", 12, {"jobId": "job-1"})
    name, event_id, data = validate_event(event)
    assert (name, event_id) == ("jobUpdated", 12)


def test_u64_boundary_and_json_precision():
    big = 9007199254740993  # 2**53 + 1, not representable as a JS double
    encoded = u64(big)
    assert encoded == "9007199254740993"
    line = encode_line({"sampleIndex": encoded})
    decoded = decode_line(line.rstrip(b"\n"))
    assert parse_u64(decoded["sampleIndex"], "sampleIndex") == big
    assert u64((1 << 64) - 1) == "18446744073709551615"
    for bad in (-1, 1 << 64, True, 1.5, "1e3", "abc"):
        with pytest.raises(BackendError):
            parse_u64(bad, "x")
