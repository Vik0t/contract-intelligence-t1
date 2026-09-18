from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
import logging
import threading
from typing import Callable

import backend.database as database

logger = logging.getLogger(__name__)


class JobManager:
    """Small durable job runner for the single-GPU local deployment.

    The database is the source of truth. The executor only performs work for
    queued rows, so a restart can recover interrupted jobs. A real multi-worker
    deployment should replace this class with Redis/Celery/RQ and keep one GPU
    worker per device.
    """

    def __init__(
        self,
        engine,
        handler: Callable[[str, int], None],
        *,
        max_workers: int = 1,
        max_attempts: int = 3,
        stale_after_minutes: int = 30,
    ) -> None:
        self.engine = engine
        self.handler = handler
        self.max_attempts = max_attempts
        self.stale_after = timedelta(minutes=stale_after_minutes)
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="contract-job",
        )
        self._lock = threading.Lock()
        self._futures: dict[int, Future] = {}
        self._timers: set[threading.Timer] = set()
        self._shutdown = False

    def enqueue(self, document_id: int, kind: str):
        db = database.get_session(self.engine)
        try:
            job, created = database.create_job(
                db,
                document_id=document_id,
                kind=kind,
                max_attempts=self.max_attempts,
            )
            job_id = job.id
        finally:
            db.close()

        if created:
            self._submit(job_id)
        return job_id

    def recover(self) -> None:
        db = database.get_session(self.engine)
        try:
            database.recover_stale_jobs(
                db,
                datetime.now() - self.stale_after,
            )
            queued_ids = [job.id for job in database.get_queued_jobs(db)]
        finally:
            db.close()

        for job_id in queued_ids:
            self._submit(job_id)

    def _submit(self, job_id: int) -> None:
        with self._lock:
            if self._shutdown:
                return
            future = self._futures.get(job_id)
            if future is not None and not future.done():
                return
            future = self.executor.submit(self._run, job_id)
            self._futures[job_id] = future
            future.add_done_callback(
                lambda _future, completed_job_id=job_id: self._forget_future(completed_job_id)
            )

    def _forget_future(self, job_id: int) -> None:
        with self._lock:
            self._futures.pop(job_id, None)

    def _run(self, job_id: int) -> None:
        db = database.get_session(self.engine)
        try:
            job = database.get_job(db, job_id)
            if not job or job.status != "queued":
                return

            job.status = "running"
            job.attempts += 1
            job.started_at = datetime.now()
            job.error = None
            db.commit()
            document_id = job.document_id
            kind = job.kind
            max_attempts = job.max_attempts
        finally:
            db.close()

        try:
            self.handler(kind, document_id)
            check_db = database.get_session(self.engine)
            try:
                document = database.get_document(check_db, document_id)
                failed = document is not None and document.processing_status == "failed"
                error = document.processing_error if failed else None
            finally:
                check_db.close()

            if failed:
                raise RuntimeError(error or "Обработка документа завершилась ошибкой")
            self._finish(job_id, status="completed")
        except Exception as exc:
            logger.exception("Processing job %s failed", job_id)
            if self._retry(job_id, str(exc), max_attempts):
                return
            self._finish(job_id, status="failed", error=str(exc))

    def _retry(self, job_id: int, error: str, max_attempts: int) -> bool:
        db = database.get_session(self.engine)
        try:
            job = database.get_job(db, job_id)
            if not job or job.attempts >= max_attempts:
                return False
            delay = 2 ** job.attempts
            job.status = "queued"
            job.started_at = None
            job.error = error[:2000]
            job.available_at = datetime.now() + timedelta(seconds=delay)
            db.commit()
            return self._schedule_retry(job_id, delay)
        finally:
            db.close()

    def _schedule_retry(self, job_id: int, delay: int) -> bool:
        timer: threading.Timer

        def submit_retry() -> None:
            with self._lock:
                self._timers.discard(timer)
            self._submit(job_id)

        timer = threading.Timer(delay, submit_retry)
        timer.daemon = True
        with self._lock:
            if self._shutdown:
                return False
            self._timers.add(timer)
        timer.start()
        return True

    def _finish(self, job_id: int, *, status: str, error: str | None = None) -> None:
        db = database.get_session(self.engine)
        try:
            job = database.get_job(db, job_id)
            if not job:
                return
            job.status = status
            job.error = error[:2000] if error else None
            job.finished_at = datetime.now()
            job.active_key = None
            db.commit()
        finally:
            db.close()

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown = True
            timers = list(self._timers)
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        self.executor.shutdown(wait=True, cancel_futures=True)
