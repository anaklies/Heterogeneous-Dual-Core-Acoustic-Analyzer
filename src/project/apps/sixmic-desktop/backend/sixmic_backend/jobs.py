"""Async job manager: accepted is not completed; cancel is a request until stopped."""
from __future__ import annotations

import threading
import time
from typing import Any

from .errors import BackendError
from .model.dto import JobState

TERMINAL = frozenset({"completed", "failed", "canceled"})


class JobManager:
    def __init__(self, storage: Any = None, *, dedupe_seconds: float = 120.0) -> None:
        self._jobs: dict[str, JobState] = {}
        self._order: list[str] = []
        self._counter = 0
        self._lock = threading.RLock()
        self._storage = storage
        self._dedupe: dict[str, tuple[str, float]] = {}
        self._dedupe_seconds = dedupe_seconds
        self.storage_errors = 0

    def create(self, *, kind: str, request_id: str,
               client_task_key: str | None = None) -> JobState:
        now = time.monotonic_ns()
        with self._lock:
            if client_task_key:
                previous = self._dedupe.get(client_task_key)
                if previous is not None and (now - previous[1]) < self._dedupe_seconds * 1e9:
                    job = self._jobs.get(previous[0])
                    if job is not None:
                        return job
            self._counter += 1
            job_id = f"job-{self._counter:06d}"
            job = JobState(job_id=job_id, kind=kind, state="accepted",
                           created_monotonic_ns=now, updated_monotonic_ns=now,
                           client_task_key=client_task_key, request_id=request_id)
            self._jobs[job_id] = job
            self._order.append(job_id)
            if client_task_key:
                self._dedupe[client_task_key] = (job_id, now)
        self._persist(job)
        return job

    def update_from_notification(self, data: dict[str, Any]) -> JobState:
        job_id = str(data.get("jobId", ""))
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = JobState.from_dict({"jobId": job_id,
                                          "kind": data.get("kind", "unknown"),
                                          "state": data.get("state", "accepted")})
                self._jobs[job_id] = job
                self._order.append(job_id)
            previous_state = job.state
            job.state = str(data.get("state", job.state))
            job.progress = data.get("progress", job.progress)
            job.updated_monotonic_ns = int(time.monotonic_ns())
            job.result = data.get("result", job.result)
            error = data.get("error")
            job.error = None if error is None else __import__(
                "sixmic_backend.model.dto", fromlist=["ErrorInfo"]).ErrorInfo.from_error(error)
            job.cancel_requested = bool(data.get("cancelRequested", job.cancel_requested))
            job.cancel_acknowledged = bool(data.get("cancelAcknowledged",
                                                   job.cancel_acknowledged))
            if job.state == "cancel_requested":
                job.cancel_requested = True
            if previous_state not in TERMINAL and job.state in TERMINAL:
                job.progress = 1.0 if job.state == "completed" else job.progress
        self._persist(job)
        return job

    def request_cancel(self, job_id: str) -> JobState:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise BackendError("job_not_found", {"jobId": job_id})
            if job.state in TERMINAL:
                raise BackendError("bad_state", {"reason": "job-already-terminal",
                                                "state": job.state})
            job.cancel_requested = True
            if job.state != "cancel_requested":
                job.state = "cancel_requested"
                job.updated_monotonic_ns = int(time.monotonic_ns())
        self._persist(job)
        return job

    def get(self, job_id: str) -> JobState:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise BackendError("job_not_found", {"jobId": job_id})
            return job

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [self._jobs[job_id] for job_id in self._order[-limit:]]
        return [job.to_dict() for job in reversed(jobs)]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            pending = sum(1 for job in self._jobs.values() if not job.terminal)
            return {"total": len(self._jobs), "pending": pending,
                    "dedupeKeys": len(self._dedupe)}

    def _persist(self, job: JobState) -> None:
        if self._storage is None:
            return
        try:
            self._storage.save_job(job.to_dict())
        except BackendError:
            self.storage_errors += 1
