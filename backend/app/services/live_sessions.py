"""Recoverable recording drafts on disk; SQL meetings only exist with a transcript.

Requires one host and a shared DATA_DIR, like the meeting processing worker.
Manifests are never served as static files. Atomic replacement and separate
short metadata locks allow attendance callbacks while transcription runs.
"""
import json
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from filelock import FileLock, Timeout
from fastapi import HTTPException
from app.config import settings
from app.database import SessionLocal
from app.models import Meeting, MeetingParticipant, MeetingTeam, TeamMember, User

logger = logging.getLogger(__name__)


def folder():
    path = Path(settings.data_dir) / "live-sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path(session_id):
    try:
        canonical = str(uuid.UUID(str(session_id)))
    except ValueError:
        raise HTTPException(404, "Live session not found")
    return folder() / f"{canonical}.json"


def read_session(session_id):
    try:
        return json.loads(session_path(session_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "Live session not found")


def save_session(data):
    path = session_path(data["session_id"])
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def edit_session(session_id):
    try:
        with FileLock(str(session_path(session_id).with_suffix(".lock")), timeout=5):
            data = read_session(session_id)
            yield data
            save_session(data)
    except Timeout:
        raise HTTPException(409, "Session is busy. Please retry.")


def new_session(title, user_id, language="auto", vocabulary="", invited_user_ids=None, team_ids=None):
    session_id = str(uuid.uuid4())
    data = dict(
        session_id=session_id,
        title=title.strip(),
        organizer_id=user_id,
        room="meetingbrain" + uuid.UUID(session_id).hex,
        created_at=datetime.now(timezone.utc).isoformat(),
        language=language,
        vocabulary=vocabulary.strip(),
        participant_ids=[],
        invited_user_ids=sorted(set(invited_user_ids or [])),
        team_ids=sorted(set(team_ids or [])),
        status="draft",
        recording_path=None,
        meeting_id=None,
        processing_error=None,
    )
    save_session(data)
    return data


def admission_open(data):
    return data["status"] == "draft" and not data.get("ended_at") and datetime.now(timezone.utc) < (
        datetime.fromisoformat(data["created_at"]) + timedelta(hours=24))


def check_employee(user):
    if user.role not in {"employee", "admin"}:
        raise HTTPException(403, "An active employee account is required")


def check_owner(data, user):
    if user.id != data["organizer_id"]:
        raise HTTPException(403, "Only the meeting organizer can save or retry its recording")


def has_user_history(user_id):
    """Pending drafts are history too; retain the account until they are saved."""
    for path in folder().glob("*.json"):
        data = read_session(path.stem)
        if data["organizer_id"] == user_id or user_id in data["participant_ids"]:
            return True
    return False


def user_has_session_access(data, user, db):
    check_employee(user)
    if user.id == data["organizer_id"] or user.id in data.get("participant_ids", []):
        return True

    # Legacy drafts created before access lists existed remain visible while live.
    explicit_access = "invited_user_ids" in data or "team_ids" in data
    if not explicit_access:
        return admission_open(data)

    if user.id in data.get("invited_user_ids", []):
        return True

    team_ids = data.get("team_ids", [])
    if team_ids:
        membership = (
            db.query(TeamMember.id)
            .filter(
                TeamMember.user_id == user.id,
                TeamMember.team_id.in_(team_ids),
            )
            .first()
        )
        if membership:
            return True

    return False


def check_view(data, user, db):
    if user_has_session_access(data, user, db):
        return
    raise HTTPException(
        403,
        "You are not selected for this meeting or one of its assigned teams.",
    )


def pending_sessions():
    for path in folder().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["status"] == "processing":
                yield data["session_id"]
        except (OSError, ValueError, KeyError):
            logger.exception("Cannot read live session manifest %s", path.name)


def recover_announcements():
    from app.services.notifications import announce_live_session
    for path in folder().glob("*.json"):
        try:
            data = read_session(path.stem)
            if data.get("started_at") and admission_open(data):
                with edit_session(path.stem) as current, SessionLocal() as db:
                    if admission_open(current):
                        announce_live_session(current, db)
        except Exception:
            logger.exception("Live announcement recovery failed for %s", path.stem)


def process_session(session_id):
    """Idempotent promotion: audio -> transcript -> SQL meeting + attendees -> RAG."""
    meeting_id = None
    try:
        with FileLock(str(session_path(session_id).with_suffix(".processing.lock")), timeout=0):
            try:
                data = read_session(session_id)
                if data["status"] != "processing":
                    return
                from app.services.transcription import transcribe_audio
                cache = session_path(session_id).with_suffix(".transcript.txt")
                if cache.exists():
                    transcript = cache.read_text(encoding="utf-8")
                else:
                    transcript = transcribe_audio(data["recording_path"], language=data["language"],
                                                 vocabulary=data.get("vocabulary", ""))
                    if not transcript.strip():
                        raise ValueError("No speech detected. Upload an audible recording.")
                    temporary = cache.with_suffix(".part")
                    with temporary.open("w", encoding="utf-8") as stream:
                        stream.write(transcript)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, cache)
                if not transcript.strip():
                    raise ValueError("The saved transcript is empty")
                # Read the latest attendance under the same lock used by join callbacks.
                with edit_session(session_id) as current, SessionLocal() as db:
                    source = "live:" + session_id
                    meeting = db.query(Meeting).filter_by(source_id=source).first()
                    if not meeting:
                        organizer = db.get(User, current["organizer_id"])
                        if not organizer:
                            raise ValueError("The organizer account no longer exists")
                        meeting = Meeting(title=current["title"],
                            meeting_date=datetime.fromisoformat(current["created_at"]),
                            organizer_id=organizer.id, source_id=source,
                            transcript=transcript, recording_path=current["recording_path"], status="processing")
                        db.add(meeting)
                        db.flush()
                    # Reconcile attendance even when recovering after SQL committed but
                    # the manifest write failed. A late join may have landed in between.
                    assigned = {
                        row[0]
                        for row in db.query(MeetingParticipant.user_id)
                        .filter_by(meeting_id=meeting.id)
                        .all()
                    }
                    access_users = set(current.get("participant_ids", [])) | set(
                        current.get("invited_user_ids", [])
                    )
                    for user_id in access_users - assigned:
                        user = db.get(User, user_id)
                        if user and user.role == "employee":
                            db.add(
                                MeetingParticipant(
                                    meeting_id=meeting.id,
                                    user_id=user_id,
                                )
                            )

                    assigned_teams = {
                        row[0]
                        for row in db.query(MeetingTeam.team_id)
                        .filter_by(meeting_id=meeting.id)
                        .all()
                    }
                    for team_id in set(current.get("team_ids", [])) - assigned_teams:
                        db.add(MeetingTeam(meeting_id=meeting.id, team_id=team_id))

                    db.commit()  # Transcript and access rights are committed together.
                    meeting_id = meeting.id
                    current.update(meeting_id=meeting_id, status="saved", processing_error=None)
            except Exception as error:
                logger.exception("Live session transcription failed: %s", session_id)
                with edit_session(session_id) as data:
                    data.update(status="processing_failed", processing_error=str(error)[:1200])
                return
    except Timeout:
        return
    if meeting_id:
        from app.services.worker import process_pending_meeting
        process_pending_meeting(meeting_id)
