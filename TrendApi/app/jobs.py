"""Background download jobs.

One worker thread runs jobs one at a time, so we never hammer NASA's servers or
write to the same cube from two places. Job state lives in memory: restarting
the server forgets job history, but downloaded data stays on disk.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from earthtrends import catalog, data


@dataclass
class Job:
    id: str
    variable: str
    start: str
    end: str
    status: str = "queued"  # queued | downloading | building | done | error
    message: str = "Waiting to start"
    done: int = 0
    total: int = 0
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["progress"] = round(self.done / self.total, 3) if self.total else None
        return d


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fetch")


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def all_jobs() -> list[Job]:
    return sorted(_jobs.values(), key=lambda j: j.created, reverse=True)


def active_for(collection: str) -> Job | None:
    for j in _jobs.values():
        if j.status in ("queued", "downloading", "building") and \
                catalog.VARIABLES[j.variable].collection == collection:
            return j
    return None


def submit(var_key: str, start: str, end: str) -> tuple[Job, bool]:
    """Queue a download. Returns (job, created). If a job for the same NASA collection
    is already running, that job is returned instead of starting a second one."""
    var = catalog.VARIABLES[var_key]
    with _lock:
        existing = active_for(var.collection)
        if existing:
            return existing, False
        job = Job(id=uuid.uuid4().hex[:12], variable=var_key, start=start, end=end)
        _jobs[job.id] = job
    _pool.submit(_run, job)
    return job, True


def _run(job: Job) -> None:
    var = catalog.VARIABLES[job.variable]

    def on_download(done: int, total: int) -> None:
        job.done, job.total = done, total
        job.message = f"Downloaded {done} of {total} months from NASA"

    try:
        if data.coverage(var, job.start, job.end)["download_months"] > 0:
            job.status, job.message = "downloading", "Connecting to NASA Earthdata"
            data.download(var, job.start, job.end, interactive=False, progress=on_download)

        # Every variable stored in the same NASA files gets its cube updated too
        # (e.g. fetching soil moisture also makes evapotranspiration available).
        siblings = [v for v in catalog.VARIABLES.values() if v.collection == var.collection]
        job.status = "building"
        for v in siblings:
            def on_build(done: int, total: int, name=v.name) -> None:
                job.done, job.total = done, total
                job.message = f"Preparing {name}: {done} of {total} months"
            data.build_cube(v, progress=on_build)

        job.status, job.message = "done", "Data ready"
    except Exception as e:  # report every failure to the client instead of dying silently
        job.status, job.error = "error", str(e)
        job.message = "Download failed"
    finally:
        job.finished = time.time()
