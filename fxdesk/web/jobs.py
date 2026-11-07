"""Small in-memory background job manager for long-running research tasks."""

from __future__ import annotations

import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(
            max_workers=max(int(max_workers), 1), thread_name_prefix="fxdesk-job"
        )
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        func: Callable[..., Any],
        *args: Any,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        job_id = uuid.uuid4().hex[:12]
        job: dict[str, Any] = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "params": params or {},
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job

        self._executor.submit(self._run, job_id, func, args, kwargs)
        return job_id

    def _run(
        self,
        job_id: str,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "running"
            job["started_at"] = _now()

        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - surface the message to clients
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "failed"
                job["error"] = str(exc)
                job["traceback"] = traceback.format_exc()
                job["finished_at"] = _now()
            return

        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "succeeded"
            job["result"] = result
            job["finished_at"] = _now()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(), key=lambda item: item["created_at"], reverse=True
            )
            return [
                {key: value for key, value in dict(job).items() if key != "result"}
                for job in jobs[: int(limit)]
            ]

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
