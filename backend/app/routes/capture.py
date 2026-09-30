"""Browser recordings enter the same durable pipeline as uploaded transcripts."""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from filelock import Timeout
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import Meeting
from app.security.auth import require_role, get_current_user
from app.routes.meetings import check_meeting_access, process_meeting_background
from app.schemas.meeting import MeetingResponse
from app.services.worker import meeting_lock

router = APIRouter(prefix="/api/capture", tags=["Recording"])


class CaptureCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


@router.post("/")
def create_capture(payload: CaptureCreate, user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    from app.routes.live import create_live, LiveCreate
    return create_live(LiveCreate(title=payload.title), user, db)


@router.get("/{meeting_id}")
def capture_info(meeting_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    check_meeting_access(meeting_id, user, db)
    # Legacy public Jitsi links must never reopen an unrestricted room.
    return {"id": meeting.id, "title": meeting.title, "meeting_url": None,
            "domain": settings.jitsi_domain, "status": meeting.status,
            "max_audio_mb": settings.max_audio_mb, "can_record": user.role == "admin"}


@router.post("/{meeting_id}/audio", response_model=MeetingResponse)
def upload_audio(meeting_id: int, background_tasks: BackgroundTasks,
                 audio: UploadFile = File(...), user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    try:
        with meeting_lock(meeting_id):
            db.refresh(meeting)
            # Retrying after an ambiguous network response must not duplicate processing.
            if meeting.recording_path:
                return meeting
            if meeting.transcript or meeting.status == "processing":
                raise HTTPException(409, "This meeting already has transcript data. Create a new meeting for this recording.")
            suffix = Path(audio.filename or "audio.webm").suffix.lower()
            if suffix not in {".webm", ".wav", ".mp3", ".m4a", ".mp4", ".ogg"}:
                raise HTTPException(415, "Use a WebM, WAV, MP3, M4A, MP4 or OGG recording")
            folder = Path(settings.data_dir) / "recordings"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (uuid.uuid4().hex + suffix)
            temporary = path.with_suffix(".part")
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
                if size == 0:
                    raise HTTPException(400, "Recording is empty")
                temporary.replace(path)
                meeting.recording_path = str(path.resolve())
                meeting.status = "processing"
                meeting.processing_error = None
                db.commit()  # Audio and queue state survive a restart before the task starts.
            except Exception:
                db.rollback()
                temporary.unlink(missing_ok=True)
                path.unlink(missing_ok=True)
                raise
            db.refresh(meeting)
    except Timeout:
        raise HTTPException(409, "This meeting is busy; retry in a moment")
    background_tasks.add_task(process_meeting_background, meeting_id)
    return meeting
