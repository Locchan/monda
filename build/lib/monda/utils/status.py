import threading
import time
from dataclasses import dataclass, field

_lock = threading.Lock()
_workers: dict[str, "WorkerEntry"] = {}
_jobs: dict[str, "JobEntry"] = {}


@dataclass
class WorkerEntry:
    name: str
    detail: str = "Starting..."
    started_at: float = field(default_factory=time.time)
    last_restart_at: float | None = None
    restart_count: int = 0
    crashed_at: float | None = None
    crash_error: str | None = None
    warning: bool = False

    def color(self) -> str:
        if self.crashed_at is not None:
            return "red"
        if self.warning or (self.last_restart_at and (time.time() - self.last_restart_at) < 86400):
            return "yellow"
        return "green"


@dataclass
class JobEntry:
    name: str
    detail: str = "Has not been executed yet."
    last_run_at: float | None = None
    last_run_duration: float | None = None
    last_run_ok: bool | None = None
    next_run_at: float | None = None
    run_count: int = 0

    def color(self) -> str:
        return "red" if self.last_run_ok is False else "green"


def get_or_create_worker(name: str) -> tuple["WorkerEntry", bool]:
    with _lock:
        is_new = name not in _workers
        if is_new:
            _workers[name] = WorkerEntry(name=name)
        return _workers[name], is_new


def get_or_create_job(key: str) -> "JobEntry":
    with _lock:
        if key not in _jobs:
            _jobs[key] = JobEntry(name=key)
        return _jobs[key]


def snapshot() -> dict:
    now = time.time()
    with _lock:
        return {
            "workers": {k: _worker_dict(v, now) for k, v in _workers.items()},
            "jobs": {k: _job_dict(v, now) for k, v in _jobs.items()},
        }


def _worker_dict(e: WorkerEntry, now: float) -> dict:
    return {
        "color": e.color(),
        "detail": e.detail,
        "uptime_seconds": now - e.started_at,
        "restart_count": e.restart_count,
        "last_restart_ago": (now - e.last_restart_at) if e.last_restart_at else None,
        "crashed_ago": (now - e.crashed_at) if e.crashed_at else None,
        "crash_error": e.crash_error,
    }


def _job_dict(e: JobEntry, now: float) -> dict:
    return {
        "color": e.color(),
        "detail": e.detail,
        "run_count": e.run_count,
        "last_run_ago": (now - e.last_run_at) if e.last_run_at else None,
        "last_run_duration": e.last_run_duration,
        "last_run_ok": e.last_run_ok,
        "next_run_in": (e.next_run_at - now) if e.next_run_at else None,
    }
