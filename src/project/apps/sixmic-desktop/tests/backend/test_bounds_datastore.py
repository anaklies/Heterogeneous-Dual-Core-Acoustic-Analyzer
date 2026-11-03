"""Bounded queues, byte budgets and owned buffer handles (no silent loss)."""
from __future__ import annotations

import pytest

from sixmic_backend.data.bounds import BoundedQueue, ByteBudget
from sixmic_backend.data.data_store import DataStore
from sixmic_backend.errors import BackendError


def test_bounded_queue_drops_oldest_and_counts():
    queue: BoundedQueue[int] = BoundedQueue(3, "live", drop_policy="oldest")
    assert queue.put(1) == 0
    queue.put(2)
    queue.put(3)
    assert queue.put(4) == 1
    assert queue.dropped == 1
    assert len(queue) == 3
    assert [queue.get() for _ in range(3)] == [2, 3, 4]
    assert queue.stats()["dropped"] == 1


def test_bounded_queue_drops_newest_policy():
    queue: BoundedQueue[int] = BoundedQueue(1, "recording", drop_policy="newest")
    queue.put(1)
    assert queue.put(2) == 1
    assert queue.get() == 1


def test_byte_budget_tracks_peak_and_rejections():
    budget = ByteBudget(10, "pcm")
    assert budget.acquire(6)
    assert budget.acquire(6) is False
    assert budget.rejected == 6
    budget.release(6)
    assert budget.acquire(10)
    assert budget.stats()["peakBytes"] == 10


def test_data_store_reference_counting_and_capacity():
    store = DataStore(capacity_bytes=1024)
    handle = store.put(b"abc" * 100, "uint8")
    store.reference(handle)
    assert store.release(handle) is False
    assert store.release(handle) is True
    with pytest.raises(BackendError) as info:
        store.put(b"x" * 2048, "uint8")
    assert info.value.code == "storage_full"
    stats = store.stats()
    assert stats["rejected"] == 1


def test_data_store_slice_and_sha():
    store = DataStore()
    handle = store.put(b"0123456789abcdef", "uint8")
    assert store.read_slice(handle, 2, 4) == b"2345"
    assert store.get(handle).sha256 is not None
    with pytest.raises(BackendError):
        store.read_slice(handle, 14, 4)
    store.release(handle)


def test_display_only_buffers_have_no_sha():
    store = DataStore()
    handle = store.put(b"display" * 10, "float32", display_only=True,
                       source_kind="test-fixture")
    assert store.get(handle).sha256 is None
    store.release(handle)


def test_invalid_element_type_releases_reserved_budget():
    """F-03: a rejected put() must not permanently reserve capacity."""
    store = DataStore(capacity_bytes=1024)
    with pytest.raises(BackendError) as info:
        store.put(b"x" * 64, "not-a-type")
    assert info.value.code == "bad_args"
    stats = store.stats()
    assert stats["usedBytes"] == 0
    assert stats["handles"] == 0
    # The whole capacity must still be available afterwards.
    handle = store.put(b"y" * 1024, "uint8")
    store.release(handle)
    assert store.stats()["usedBytes"] == 0
