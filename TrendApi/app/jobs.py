"""Background analysis jobs.

Analyses that stream from NASA's cloud take ~30 s, too long for one HTTP request
to feel responsive, so they run here and the client polls GET /jobs/{id} for
progress and the result. A couple of workers run at once; extra jobs queue.

Job state lives in memory (the newest MAX_JOBS are kept). Nothing is written to
disk, so many users can't fill the server's storage.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

WORKERS = 2
MAX_JOBS = 50


@dataclass
class Job:
    id: str
    variable: str
    start: str | None
    end: str | None
    status: str = "queued"  # queued | running | done | error
    message: str = "Waiting for a free worker"
    done: int = 0
    total: int = 0
    error: str | None = None
    result: dict | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "variable": self.variable, "start": self.start, "end": self.end,
            "status": self.status, "message": self.message, "done": self.done, "total": self.total,
            "progress": round(self.done / self.total, 3) if self.total else None,
            "error": self.error, "result": self.result,
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="analyze")


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def submit(variable: str, start: str | None, end: str | None,
           work: Callable[..., dict],
           on_error: Callable[[Exception], str]) -> Job:
    """Run work(progress) - or work(progress, say) if it takes two arguments - in the
    background. progress(done, total) reports NASA streaming; say(message) sets a status
    line for other steps. on_error turns an exception into a message."""
    job = Job(id=uuid.uuid4().hex[:12], variable=variable, start=start, end=end)
    with _lock:
        _jobs[job.id] = job
        for old in sorted(_jobs.values(), key=lambda j: j.created)[:-MAX_JOBS]:
            _jobs.pop(old.id, None)

    def progress(done: int, total: int) -> None:
        job.done, job.total = done, total
        job.message = f"Streaming from NASA Earthdata Cloud: {done} of {total} months"

    def say(message: str) -> None:
        job.message = message
        job.done = job.total = 0

    def run() -> None:
        job.status, job.message = "running", "Finding data"
        try:
            import inspect
            takes_say = len(inspect.signature(work).parameters) >= 2
            job.result = work(progress, say) if takes_say else work(progress)
            job.status, job.message = "done", "Analysis complete"
        except Exception as e:
            job.status, job.error, job.message = "error", on_error(e), "Analysis failed"
        finally:
            job.finished = time.time()

    _pool.submit(run)
    return job
