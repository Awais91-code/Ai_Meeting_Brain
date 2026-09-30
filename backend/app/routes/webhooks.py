import hashlib
import hmac
import json
from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
)
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import get_db
from app.models import Meeting, MeetingParticipant, User
from app.routes.meetings import process_meeting_background
from app.services.zoom import (
    download_transcript_vtt,
    find_transcript_file,
    vtt_to_plain_text,
)

router = APIRouter(
    prefix="/api/webhooks",
    tags=["Webhooks"],
)


class WebhookMeetingPayload(BaseModel):
    """
    API contract for automatic meeting creation from an external
    automation tool (n8n, sitting between Zoom/Google Meet/Teams and
    this backend).

    n8n's job: receive the meeting event, extract the transcript and
    participant emails, and POST this shape here.

    This backend's job: validate it, create the meeting, resolve
    participant emails to existing employee accounts, and kick off the
    normal automatic processing pipeline (chunk -> embed -> ChromaDB
    -> summary) exactly like a manual transcript upload would.
    """

    title: str
    meeting_date: datetime
    duration_minutes: int | None = None
    transcript: str
    organizer_email: EmailStr | None = None
    participant_emails: list[EmailStr] = []
    external_id: str | None = None
    source: str | None = None  # e.g. "zoom", "google_meet", "teams"


def _verify_webhook_secret(x_webhook_secret: str | None) -> None:
    if not settings.n8n_webhook_secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "The automation webhook is not configured. Set "
                "N8N_WEBHOOK_SECRET in the environment to enable it."
            ),
        )

    if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, settings.n8n_webhook_secret):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing webhook secret.",
        )


def _resolve_organizer(db: Session, organizer_email: str | None) -> User:
    """Explicit email if given and it belongs to an account, otherwise
    fall back to the first admin account (every deployment has one)."""

    organizer = None

    if organizer_email:
        organizer = db.query(User).filter(User.email == organizer_email).first()

    if organizer is None:
        organizer = db.query(User).filter(User.role == "admin").first()

    if organizer is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "No admin account exists to own automatically created "
                "meetings. Create at least one admin account first."
            ),
        )

    return organizer


def _create_meeting_and_assign(
    db: Session,
    background_tasks: BackgroundTasks,
    title: str,
    meeting_date: datetime,
    duration_minutes: int | None,
    transcript: str,
    organizer_email: str | None,
    participant_emails: list[str],
    source_id: str | None = None,
) -> dict:
    """Shared logic for both the generic n8n webhook and the Zoom
    webhook: create the meeting, resolve participants by email, and
    kick off the same automatic processing pipeline a manual
    transcript upload would use."""

    transcript = transcript.strip()

    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript cannot be empty.")

    if source_id:
        existing = db.query(Meeting).filter_by(source_id=source_id).first()
        if existing:
            return {"meeting_id": existing.id, "status": existing.status, "duplicate": True}
    organizer = _resolve_organizer(db, organizer_email)

    meeting = Meeting(
        title=title,
        source_id=source_id,
        meeting_date=meeting_date,
        duration_minutes=duration_minutes,
        organizer_id=organizer.id,
        transcript=transcript,
        status="processing",
    )

    db.add(meeting)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(Meeting).filter_by(source_id=source_id).first() if source_id else None
        if not existing:
            raise
        return {"meeting_id": existing.id, "status": existing.status, "duplicate": True}

    assigned, skipped = [], []

    for email in participant_emails:
        user = db.query(User).filter(User.email == email).first()

        if user is None:
            skipped.append(email)
            continue

        exists = (
            db.query(MeetingParticipant)
            .filter(
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.user_id == user.id,
            )
            .first()
        )

        if exists:
            continue

        db.add(MeetingParticipant(meeting_id=meeting.id, user_id=user.id))
        assigned.append(email)

    db.commit()

    background_tasks.add_task(process_meeting_background, meeting.id)

    return {
        "meeting_id": meeting.id,
        "status": meeting.status,
        "organizer_email": organizer.email,
        "participants_assigned": assigned,
        "participants_skipped_not_found": skipped,
    }


@router.post("/n8n/meetings")
def create_meeting_from_webhook(
    payload: WebhookMeetingPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None),
):
    _verify_webhook_secret(x_webhook_secret)

    result = _create_meeting_and_assign(
        db=db,
        background_tasks=background_tasks,
        title=payload.title,
        meeting_date=payload.meeting_date,
        duration_minutes=payload.duration_minutes,
        transcript=payload.transcript,
        organizer_email=payload.organizer_email,
        participant_emails=payload.participant_emails,
        source_id="webhook:" + hashlib.sha256(((payload.source or "generic") + ":" +
            (payload.external_id or payload.model_dump_json())).encode()).hexdigest(),
    )

    result["message"] = "Meeting created. Automatic processing started."
    return result


# ============================================================
# ZOOM INTEGRATION
# ============================================================
# Zoom -> "recording.completed" webhook -> this endpoint -> download
# the auto-generated transcript -> create meeting -> normal processing
# pipeline. See app/services/zoom.py for the full setup instructions.

@router.post("/zoom")
async def zoom_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event = payload.get("event")

    # ------------------------------------------------------------
    # 1. Zoom's one-time "URL validation" handshake — required before
    #    Zoom will activate the webhook subscription. Must respond
    #    with the plainToken plus an HMAC-SHA256 of it, NOT verified
    #    against the usual signature headers (there are none yet).
    # ------------------------------------------------------------
    if event == "endpoint.url_validation":
        if not settings.zoom_webhook_secret_token:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Zoom webhook is not configured. Set "
                    "ZOOM_WEBHOOK_SECRET_TOKEN in the environment."
                ),
            )

        plain_token = payload.get("payload", {}).get("plainToken", "")

        encrypted_token = hmac.new(
            settings.zoom_webhook_secret_token.encode(),
            plain_token.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "plainToken": plain_token,
            "encryptedToken": encrypted_token,
        }

    # ------------------------------------------------------------
    # 2. Every other event: verify Zoom's request signature.
    #    Formula per Zoom's docs: v0=HMAC_SHA256(secret, f"v0:{ts}:{body}")
    # ------------------------------------------------------------
    _verify_zoom_signature(request, raw_body)

    # ------------------------------------------------------------
    # 3. We only care about "recording.completed" — every other
    #    subscribed event (meeting.started, meeting.ended, etc.) is
    #    acknowledged but ignored, since the transcript only exists
    #    once Zoom finishes generating the cloud recording.
    # ------------------------------------------------------------
    if event not in {"recording.completed", "recording.transcript_completed"}:
        return {"message": f"Event '{event}' received but not handled."}

    zoom_object = payload.get("payload", {}).get("object", {})

    recording_files = zoom_object.get("recording_files", [])
    transcript_file = find_transcript_file(recording_files)

    if transcript_file is None:
        return {
            "message": (
                "recording.completed received, but no TRANSCRIPT file "
                "was found. Waiting for recording.transcript_completed. Enable 'Audio transcript' in the Zoom "
                "account's cloud recording settings."
            )
        }

    try:
        vtt_content = download_transcript_vtt(transcript_file["download_url"])
        transcript_text = vtt_to_plain_text(vtt_content)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Could not download/parse Zoom transcript: {error}",
        )

    start_time_raw = zoom_object.get("start_time")
    if start_time_raw:
        # Zoom sends e.g. "2026-09-01T10:00:00Z"
        meeting_date = datetime.fromisoformat(
            start_time_raw.replace("Z", "+00:00")
        )
    else:
        meeting_date = datetime.utcnow()

    result = _create_meeting_and_assign(
        db=db,
        background_tasks=background_tasks,
        title=zoom_object.get("topic", "Zoom Meeting"),
        meeting_date=meeting_date,
        duration_minutes=zoom_object.get("duration"),
        transcript=transcript_text,
        organizer_email=zoom_object.get("host_email"),
        # Zoom's recording.completed payload does not include the
        # attendee list — participants must still be assigned manually
        # in the admin panel (or extended later using Zoom's Reports
        # API to look up past-meeting participants by meeting UUID).
        participant_emails=[],
        source_id="zoom:" + str(zoom_object.get("uuid") or hashlib.sha256(transcript_text.encode()).hexdigest()),
    )

    result["message"] = "Zoom recording processed. Automatic processing started."
    return result


def _verify_zoom_signature(request: Request, raw_body: bytes) -> None:
    if not settings.zoom_webhook_secret_token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Zoom webhook is not configured. Set "
                "ZOOM_WEBHOOK_SECRET_TOKEN in the environment."
            ),
        )

    timestamp = request.headers.get("x-zm-request-timestamp")
    signature = request.headers.get("x-zm-signature")

    if not timestamp or not signature:
        raise HTTPException(
            status_code=401, detail="Missing Zoom signature headers."
        )

    message = f"v0:{timestamp}:{raw_body.decode()}"

    expected_hash = hmac.new(
        settings.zoom_webhook_secret_token.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    expected_signature = f"v0={expected_hash}"

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=401, detail="Invalid Zoom signature.")
