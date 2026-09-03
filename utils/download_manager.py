import asyncio
import threading
import time
import uuid
from typing import Optional


class DownloadCancelled(Exception):
    pass


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class DownloadJob:
    def __init__(self, job_id: str, chat_id: int):
        self.job_id = job_id
        self.chat_id = chat_id
        self.token = CancellationToken()
        self.status = "queued"
        self.queued_at = time.time()
        self.ready_event: asyncio.Event = asyncio.Event()

    def cancel(self):
        self.token.cancel()
        self.ready_event.set()


class DownloadManager:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._lock = asyncio.Lock()
        self._jobs: dict[str, DownloadJob] = {}
        self._waiters: list[DownloadJob] = []
        self._active_count = 0

    @property
    def active_count(self) -> int:
        return self._active_count

    def queue_length(self) -> int:
        return len(self._waiters)

    def create_job(self, chat_id: int) -> DownloadJob:
        job = DownloadJob(uuid.uuid4().hex[:12], chat_id)
        self._jobs[job.job_id] = job
        return job

    def position(self, job: DownloadJob) -> Optional[int]:
        try:
            return self._waiters.index(job) + 1
        except ValueError:
            return None

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.cancel()
        return True

    def _promote_waiters(self) -> None:
        while self._waiters and self._active_count < self.max_concurrent:
            next_job = self._waiters.pop(0)
            if next_job.token.cancelled:
                continue
            self._active_count += 1
            next_job.status = "downloading"
            next_job.ready_event.set()

    async def wait_for_slot(self, job: DownloadJob, position_cb=None) -> bool:
        async with self._lock:
            if self._active_count < self.max_concurrent and not self._waiters:
                self._active_count += 1
                job.status = "downloading"
                return True
            self._waiters.append(job)
            pos = len(self._waiters)

        last_pos = pos
        if position_cb:
            try:
                await position_cb(last_pos)
            except Exception:
                pass

        try:
            while not job.ready_event.is_set():
                if job.token.cancelled:
                    return False
                try:
                    await asyncio.wait_for(job.ready_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                if job.token.cancelled:
                    return False

                async with self._lock:
                    pos = self.position(job)
                if position_cb and pos is not None and pos != last_pos:
                    last_pos = pos
                    try:
                        await position_cb(pos)
                    except Exception:
                        pass

            return not job.token.cancelled
        finally:
            if job.status != "downloading":
                async with self._lock:
                    if job in self._waiters:
                        self._waiters.remove(job)
                    self._jobs.pop(job.job_id, None)
                    self._promote_waiters()

    async def release_slot(self, job: DownloadJob):
        async with self._lock:
            if job.status == "downloading":
                self._active_count = max(0, self._active_count - 1)
            if job in self._waiters:
                self._waiters.remove(job)
            self._jobs.pop(job.job_id, None)
            job.status = "done"
            self._promote_waiters()


download_manager = DownloadManager(max_concurrent=3)

