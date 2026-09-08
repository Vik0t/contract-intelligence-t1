from __future__ import annotations

import time
from threading import Event

import backend.database as database
from backend.jobs import JobManager


def test_job_manager_is_idempotent_and_completes(tmp_path):
    engine = database.get_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    database.create_tables(engine)
    db = database.get_session(engine)
    try:
        user = database.create_user(
            db,
            username="job-user",
            email="job@example.com",
            password_hash="not-used-in-this-test",
        )
        document = database.create_document(
            db,
            owner=user.id,
            template_id=None,
            filename="contract.pdf",
        )
        document_id = document.id
    finally:
        db.close()

    calls: list[tuple[str, int]] = []
    started = Event()
    release = Event()

    def handler(kind: str, handled_document_id: int) -> None:
        calls.append((kind, handled_document_id))
        started.set()
        release.wait(timeout=5)

    manager = JobManager(engine, handler, max_workers=1)
    try:
        first_job_id = manager.enqueue(document_id, "parse")
        assert started.wait(timeout=5)
        second_job_id = manager.enqueue(document_id, "parse")
        release.set()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            check_db = database.get_session(engine)
            try:
                job = database.get_job(check_db, first_job_id)
                if job and job.status == "completed":
                    break
            finally:
                check_db.close()
            time.sleep(0.01)

        check_db = database.get_session(engine)
        try:
            job = database.get_job(check_db, first_job_id)
            assert job is not None
            assert job.status == "completed"
        finally:
            check_db.close()

        assert second_job_id == first_job_id
        assert calls == [("parse", document_id)]
    finally:
        manager.shutdown()
