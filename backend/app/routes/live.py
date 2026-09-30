"""Employee-only admission and deferred meeting persistence."""
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import Meeting, MeetingParticipant, Team, TeamMember, User
from app.security.auth import get_current_user, require_role
from app.services import live_sessions as sessions

router = APIRouter(prefix="/api/live", tags=["Live sessions"])


class LiveCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    language: Literal["auto", "en", "ur", "hi"] = "auto"
    vocabulary: str = Field(default="", max_length=500)
    participant_ids: list[int] = Field(default_factory=list)
    team_ids: list[int] = Field(default_factory=list)


def secure_conferencing():
    return bool(settings.jitsi_require_auth and len(settings.jitsi_app_secret) >= 32
                and settings.jitsi_domain.split(":")[0].lower() != "meet.jit.si")


def public_info(data, user, db):
    sessions.check_view(data, user, db)
    meeting = db.get(Meeting, data["meeting_id"]) if data["meeting_id"] else None
    organizer = db.get(User, data["organizer_id"])
    return {"session_id": data["session_id"], "title": data["title"],
            "language": data["language"], "status": meeting.status if meeting else data["status"],
            "meeting_id": meeting.id if meeting else None,
            "processing_error": meeting.processing_error if meeting else data["processing_error"],
            "can_record": user.id == data["organizer_id"], "max_audio_mb": settings.max_audio_mb,
            "can_join": sessions.admission_open(data) and secure_conferencing(),
            "conference_configured": secure_conferencing(),
            "organizer": organizer.name if organizer else "Meeting host",
            "started_at": data.get("started_at"), "ended_at": data.get("ended_at"),
            "is_live": bool(data.get("started_at") and sessions.admission_open(data)),
            "attendee_count": len(data["participant_ids"]),
            "invite_path": "/live/" + data["session_id"],
            "show_invite": user.id == data["organizer_id"],
            "selected_employee_count": len(data.get("invited_user_ids", [])),
            "selected_team_count": len(data.get("team_ids", []))}


@router.post("/")
def create_live(payload: LiveCreate, user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    if not payload.title.strip():
        raise HTTPException(400, "Meeting title cannot be empty")

    participant_ids = sorted(set(payload.participant_ids))
    team_ids = sorted(set(payload.team_ids))

    if participant_ids:
        employees = db.query(User).filter(User.id.in_(participant_ids)).all()
        valid = {
            employee.id
            for employee in employees
            if employee.role == "employee" and employee.is_active
        }
        if valid != set(participant_ids):
            raise HTTPException(
                400,
                "Meeting access can be assigned only to active employee accounts.",
            )

    if team_ids:
        teams = db.query(Team).filter(Team.id.in_(team_ids)).all()
        if {team.id for team in teams} != set(team_ids):
            raise HTTPException(400, "One or more selected teams do not exist.")

    data = sessions.new_session(
        payload.title,
        user.id,
        payload.language,
        payload.vocabulary,
        invited_user_ids=participant_ids,
        team_ids=team_ids,
    )
    return public_info(data, user, db)


@router.get("/")
def list_live(user=Depends(get_current_user), db: Session = Depends(get_db)):
    sessions.check_employee(user)
    results = []
    for path in sessions.folder().glob("*.json"):
        data = sessions.read_session(path.stem)
        if data["status"] != "saved" and sessions.user_has_session_access(data, user, db):
            results.append(public_info(data, user, db))
    return results


@router.get("/{session_id}")
def live_info(session_id: uuid.UUID, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return public_info(sessions.read_session(session_id), user, db)


@router.post("/{session_id}/admission")
def admission(
    session_id: uuid.UUID,
    response: Response,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions.check_employee(user)
    with sessions.edit_session(session_id) as data:
        sessions.check_view(data, user, db)
        if not sessions.admission_open(data):
            raise HTTPException(409, "This meeting has ended or its invitation has expired")
        if not secure_conferencing():
            raise HTTPException(503, "Employee-only conferencing needs a private Jitsi server with JWT authentication and guests disabled. Recording uploads remain available.")
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=5)
        claims = {"iss": settings.jitsi_app_id, "aud": settings.jitsi_app_id,
                  "sub": settings.jitsi_jwt_subject, "room": data["room"],
                  "iat": now, "nbf": now - timedelta(seconds=10), "exp": expiry,
                  "context": {"user": {"id": str(user.id), "name": user.name, "email": user.email}}}
        # A separate, user-bound receipt cannot be used as a conference JWT.
        receipt = jwt.encode({"sub": str(user.id), "aud": "live-attendance",
            "session_id": str(session_id), "exp": now + timedelta(hours=12)},
            settings.secret_key, algorithm="HS256")
        response.headers["Cache-Control"] = "no-store"
        conference_jwt = jwt.encode(
            claims, settings.jitsi_app_secret, algorithm="HS256"
        )
        return {
            "domain": settings.jitsi_domain,
            "room": data["room"],
            "jwt": conference_jwt,
            "receipt": receipt,
            "display_name": user.name,
            "join_url": (
                f"https://{settings.jitsi_domain}/{data['room']}"
                f"?jwt={conference_jwt}#config.prejoinConfig.enabled=false"
                "&config.disableDeepLinking=true"
            ),
        }


class Joined(BaseModel):
    receipt: str


@router.post("/{session_id}/joined")
def joined(session_id: uuid.UUID, payload: Joined, user=Depends(get_current_user), db: Session = Depends(get_db)):
    sessions.check_employee(user)
    try:
        claims = jwt.decode(payload.receipt, settings.secret_key, algorithms=["HS256"], audience="live-attendance")
        if claims.get("sub") != str(user.id) or claims.get("session_id") != str(session_id):
            raise ValueError("Wrong attendee or room")
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(403, "Invalid attendance receipt")
    with sessions.edit_session(session_id) as data:
        newly_joined = user.id not in data["participant_ids"]
        if newly_joined:
            data["participant_ids"].append(user.id)
        # Handles a delayed/retried callback racing with transcript promotion.
        if newly_joined and data["meeting_id"] and db.get(Meeting, data["meeting_id"]):
            existing = db.query(MeetingParticipant).filter_by(meeting_id=data["meeting_id"], user_id=user.id).first()
            if not existing:
                db.add(MeetingParticipant(meeting_id=data["meeting_id"], user_id=user.id))
                db.commit()
        if user.id == data["organizer_id"] and sessions.admission_open(data):
            data.setdefault("started_at", datetime.now(timezone.utc).isoformat())
            # Persist the start before fanout so recovery can finish after a crash.
            sessions.save_session(data)
            from app.services.notifications import announce_live_session
            announce_live_session(data, db)
    return {"joined": True}


@router.post("/{session_id}/end")
def end_session(session_id: uuid.UUID, user=Depends(get_current_user)):
    with sessions.edit_session(session_id) as data:
        sessions.check_owner(data, user)
        data.setdefault("ended_at", datetime.now(timezone.utc).isoformat())
    return {"ended": True}


@router.post("/{session_id}/audio")
def upload(session_id: uuid.UUID, background_tasks: BackgroundTasks, audio: UploadFile = File(...),
           user=Depends(get_current_user), db: Session = Depends(get_db)):
    with sessions.edit_session(session_id) as data:
        sessions.check_owner(data, user)
        # Idempotent after ambiguous upload responses; retry transcription separately.
        if data["status"] not in {"draft", "processing_failed"}:
            return public_info(data, user, db)
        suffix = Path(audio.filename or "audio.webm").suffix.lower()
        if suffix not in {".webm", ".wav", ".mp3", ".m4a", ".mp4", ".ogg"}:
            raise HTTPException(415, "Use WebM, WAV, MP3, M4A, MP4 or OGG audio")
        path = sessions.folder() / (str(session_id) + "-" + uuid.uuid4().hex + suffix)
        temporary = path.with_suffix(".upload")
        try:
            size = 0
            with temporary.open("wb") as output:
                while chunk := audio.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_audio_mb * 1024 * 1024:
                        raise HTTPException(413, f"Recording exceeds {settings.max_audio_mb} MB")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not size:
                raise HTTPException(400, "Recording is empty")
            os.replace(temporary, path)
            sessions.session_path(session_id).with_suffix(".transcript.txt").unlink(missing_ok=True)
            data.update(recording_path=str(path.resolve()), status="processing", processing_error=None)
            data.setdefault("ended_at", datetime.now(timezone.utc).isoformat())
        finally:
            temporary.unlink(missing_ok=True)
    background_tasks.add_task(sessions.process_session, str(session_id))
    return public_info(data, user, db)


@router.post("/{session_id}/retry")
def retry(session_id: uuid.UUID, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    with sessions.edit_session(session_id) as data:
        sessions.check_owner(data, user)
        if data["status"] != "processing_failed" or not data["recording_path"]:
            raise HTTPException(409, "Only a failed transcription can be retried here")
        data.update(status="processing", processing_error=None)
    background_tasks.add_task(sessions.process_session, str(session_id))
    return {"status": "processing"}
