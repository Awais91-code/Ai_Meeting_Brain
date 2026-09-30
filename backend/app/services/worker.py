"""Recover pending SQL work on restart. All processes share DATA_DIR locks.

Supported deployment: one host/shared local disk, one Uvicorn worker. Locks
also serialize request background tasks with the recovery poller. OS releases
locks on crash; the committed 'processing' status remains pending on restart.
"""
import logging
from pathlib import Path
from threading import Event, Thread
from functools import wraps
from filelock import FileLock, Timeout
from app.config import settings
from app.database import SessionLocal
from app.models import Meeting

logger = logging.getLogger(__name__)


def meeting_lock(meeting_id):
    folder = Path(settings.data_dir) / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    return FileLock(str(folder / f"meeting-{meeting_id}.lock"), timeout=0)


def serialized_write(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from fastapi import HTTPException
        meeting_id = kwargs.get("meeting_id", args[0] if args else None)
        try:
            with meeting_lock(meeting_id):
                return function(*args, **kwargs)
        except Timeout:
            raise HTTPException(409, "Meeting is being processed. Try again shortly.")
    return wrapped


def process_pending_meeting(meeting_id):
    try:
        with meeting_lock(meeting_id), SessionLocal() as db:
            meeting = db.get(Meeting, meeting_id)
            if meeting and meeting.status == "processing":
                from app.services.meeting_processor import process_meeting_automatically
                process_meeting_automatically(meeting_id, db)
    except Timeout:
        pass  # A request background task or another poll already owns this meeting.
    except Exception:
        logger.exception("Meeting %s processing failed", meeting_id)


def start_worker():
    stop = Event()
    def run():
        while not stop.is_set():
            try:
                from app.services.live_sessions import pending_sessions, process_session, recover_announcements
                recover_announcements()
                for session_id in pending_sessions():
                    if stop.is_set():
                        break
                    process_session(session_id)
                with SessionLocal() as db:
                    ids = [row[0] for row in db.query(Meeting.id).filter_by(status="processing").all()]
                for meeting_id in ids:
                    if stop.is_set():
                        break
                    process_pending_meeting(meeting_id)
            except Exception:
                logger.exception("Recovery poll failed; check database migrations")
            stop.wait(3)
    thread = Thread(target=run, daemon=True, name="meeting-recovery")
    thread.start()
    return stop, thread
