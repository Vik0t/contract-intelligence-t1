from __future__ import annotations

import time
from threading import Event
from datetime import datetime, timedelta

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


def test_restart_recovers_recent_running_job_and_commits_it(tmp_path):
    engine = database.get_engine(f"sqlite:///{tmp_path / 'restart.db'}")
    database.create_tables(engine)
    db = database.get_session(engine)
    user = database.create_user(db, username="restart", email="restart@example.com", password_hash="unused")
    doc = database.create_document(db, owner=user.id, template_id=None, filename="doc.pdf")
    job, _ = database.create_job(db, document_id=doc.id, kind="extract", max_attempts=3)
    job.status = "running"
    job.started_at = datetime.now() - timedelta(seconds=5)
    db.commit()
    job_id = job.id
    db.close()
    completed = Event()
    manager = JobManager(engine, lambda *_args: completed.set())
    try:
        manager.recover()
        assert completed.wait(5), "A recently interrupted job must not wait 30 minutes"
    finally:
        manager.shutdown()
    db = database.get_session(engine)
    try:
        assert database.get_job(db, job_id).status == "completed"
    finally:
        db.close()
