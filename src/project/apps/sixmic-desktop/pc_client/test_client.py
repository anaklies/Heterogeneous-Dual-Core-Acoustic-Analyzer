"""Short isolated tests; no board, socket, Qt event loop or DSP required."""
import copy
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/sixmic-desktop/backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sixmic_backend.data.data_store import DataStore
from sixmic_backend.errors import BackendError
from sixmic_backend.transport.control_client import ControlClient
from pc_client.client import FeatureClient
from pc_client.transport import request


class FakeControl:
    session_id = "session-1"

    def __init__(self):
        self.calls = []
        self.words = [0xffffffff, 0x80000000, 0x7fc00001] + list(range(1100))
        self.modify = lambda page, offset: None

    def request(self, op, args):
        self.calls.append((op, copy.deepcopy(args)))
        if op == "feature.list":
            return {"features": [{"featureId": "FFT"}], "version": 1}
        if op in {"feature.start", "feature.stop"}:
            return {"jobId": "job-1"}
        if op == "feature.get":
            return {"jobId": "job-1", "state": "completed"}
        offset = args["offsetWords"]
        words = self.words[offset:offset + args["maxWords"]]
        page = {"jobId": "job-1", "featureId": "FFT", "state": "completed",
                "sourceKind": "pl-live", "configuration": {"session": "session-1",
                "config": "1", "generation": "18446744073709551615",
                "sourceFrame": "9007199254740993"},
                "schema": {"kind": "complex-u32", "fields": [], "axes": [],
                "units": "raw", "validity": {}}, "totalWords": len(self.words),
                "offsetWords": offset, "words": words, "more": offset + len(words) < len(self.words)}
        self.modify(page, offset)
        return page


class FakeSession:
    def __init__(self):
        self.control = FakeControl()
        self.data_store = DataStore()
        self._control_token = None
        self.claims = 0

    def claim_control(self):
        self.claims += 1
        self._control_token = "owned-token"


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.client = FeatureClient(self.session)

    def test_catalog_and_control_lease(self):
        self.assertEqual(self.client.list_features()["version"], 1)
        self.client.start_feature("FFT", {"length": 1024})
        self.client.stop_feature("job-1")
        self.assertEqual(self.session.claims, 1)
        self.assertEqual(self.session.control.calls[-1][1]["controlToken"], "owned-token")

    def test_reconnect_reclaims_control_without_replay(self):
        self.client.start_feature("FFT")
        self.session.control.session_id = "session-2"
        self.client.stop_feature("job-1")
        self.assertEqual(self.session.claims, 2)
        self.assertEqual(len(self.session.control.calls), 2)

    def test_chunking_raw_bits_u64_and_owned_handle(self):
        result = self.client.get_feature_result("job-1")
        self.assertEqual(result.configuration["generation"], "18446744073709551615")
        self.assertEqual(result.configuration["sourceFrame"], "9007199254740993")
        handle = self.session.data_store.get(result.data_ref["handleId"])
        self.assertEqual(list(struct.unpack("<" + "I" * handle.count, handle.data)), self.session.control.words)
        self.assertEqual([call[1]["offsetWords"] for call in self.session.control.calls], [0, 1024])
        self.assertTrue(all(call[1]["maxWords"] <= 1024 for call in self.session.control.calls))
        self.assertNotIn("words", result.to_dict())
        self.assertTrue(self.client.release_result(result))
        self.assertEqual(self.session.data_store.budget.used, 0)

    def test_changed_generation_rejected_without_handle(self):
        self.session.control.modify = lambda page, offset: page["configuration"].update(generation=str(offset))
        with self.assertRaises(BackendError):
            self.client.get_feature_result("job-1")
        self.assertEqual(self.session.data_store.budget.used, 0)

    def test_invalid_bits_and_empty_progress_rejected(self):
        for field, value in (("words", [-1]), ("words", [True]), ("words", []), ("more", False)):
            self.session.control.modify = lambda page, offset: page.update({field: value})
            with self.assertRaises(BackendError):
                self.client.get_feature_result("job-1")

    def test_capacity_rejected_before_further_fetch(self):
        self.session.data_store = DataStore(capacity_bytes=8)
        with self.assertRaises(BackendError):
            self.client.get_feature_result("job-1")
        self.assertEqual(len(self.session.control.calls), 1)

    def test_fixture_provenance_preserved(self):
        self.session.control.modify = lambda page, offset: page.update(sourceKind="test-fixture")
        result = self.client.get_feature_result("job-1")
        self.assertEqual(result.to_dict()["sourceKind"], "test-fixture")
        self.assertEqual(result.data_ref["sourceKind"], "test-fixture")

    def test_existing_control_connection_extension_envelope(self):
        control = ControlClient("unused", auto_reconnect=False)
        control._connected.set()
        control._session_id = "authenticated-session"
        captured = []

        def fake_send(encoded):
            payload = json.loads(encoded)
            captured.append(payload)
            pending = control._pending[payload["requestId"]]
            pending.payload = {"status": "ok", "result": {"features": [], "version": 1}}
            pending.event.set()

        control._send = fake_send
        self.assertEqual(request(control, "feature.list", {})["version"], 1)
        self.assertEqual(captured[0]["sessionId"], "authenticated-session")
        self.assertEqual(captured[0]["op"], "feature.list")
        self.assertEqual(control._pending, {})


if __name__ == "__main__":
    unittest.main()
