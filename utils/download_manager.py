import asyncio
import threading
import time
import uuid


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

    def cancel(self):
        self.token.cancel()


class DownloadManager:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._lock = asyncio.Lock()
        self._jobs: dict = {}
        self._waiters: list = []
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

    def position(self, job: DownloadJob):
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

    async def wait_for_slot(self, job: DownloadJob, position_cb=None) -> bool:
        async with self._lock:
            self._waiters.append(job)
        last_pos = 0
        try:
            while True:
                if job.token.cancelled:
                    return False
                async with self._lock:
                    is_head = bool(self._waiters) and self._waiters[0] is job
                    slot_free = self._active_count < self.max_concurrent
                if slot_free and is_head:
                    async with self._lock:
                        self._waiters.pop(0)
                        self._active_count += 1
                        job.status = "downloading"
                    return True
                async with self._lock:
                    pos = self.position(job)
                if position_cb and pos != last_pos:
                    last_pos = pos
                    await position_cb(pos)
                await asyncio.sleep(0.2)
        finally:
            if job.status != "downloading":
                async with self._lock:
                    if job in self._waiters:
                        self._waiters.remove(job)
                    self._jobs.pop(job.job_id, None)

    async def release_slot(self, job: DownloadJob):
        async with self._lock:
            if job.status == "downloading":
                self._active_count -= 1
            if job in self._waiters:
                self._waiters.remove(job)
            self._jobs.pop(job.job_id, None)
            job.status = "done"


download_manager = DownloadManager(max_concurrent=3)
