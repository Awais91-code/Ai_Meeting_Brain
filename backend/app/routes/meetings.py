from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Meeting, MeetingTeam, Team, TeamMember, User, TranscriptChunk
from app.schemas.meeting import MeetingCreate, MeetingResponse, MeetingStats
from app.security.auth import (
    get_current_user,
    require_role,
)
from app.schemas.transcript import TranscriptUpdate
from app.services.transcript import chunk_transcript
from app.services.embeddings import create_embedding
from app.services.vector_store import add_chunks, delete_chunks, search
from pydantic import BaseModel, Field, field_validator
from app.services.llm import generate_answer, resolve_followup_question
from sqlalchemy import exists, select, or_
from app.models.chat_message import ChatMessage
from app.models.notification import Notification
from app.services.summary import (
    generate_structured_summary,
    structured_summary_to_text,
)
from app.models.meeting_participant import MeetingParticipant
from app.schemas.meeting_participant import (
    MeetingParticipantCreate,
    MeetingParticipantResponse,
)
from app.services.meeting_processor import (
    process_meeting_automatically,
)
from datetime import datetime
import json
from app.services.worker import serialized_write

router = APIRouter(
    prefix="/api/meetings",
    tags=["Meetings"],
)

MAX_RELEVANCE_DISTANCE = 1.2  # cosine distance (0 = identical, 2 = opposite)


def process_meeting_background(meeting_id: int):
    from app.services.worker import process_pending_meeting
    process_pending_meeting(meeting_id)


def _validate_access_targets(db: Session, participant_ids: list[int], team_ids: list[int]):
    participant_ids = sorted(set(participant_ids or []))
    team_ids = sorted(set(team_ids or []))

    if participant_ids:
        employees = db.query(User).filter(User.id.in_(participant_ids)).all()
        valid = {
            user.id
            for user in employees
            if user.role == "employee" and user.is_active
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

    return participant_ids, team_ids


def _apply_meeting_access(
    db: Session,
    meeting_id: int,
    participant_ids: list[int],
    team_ids: list[int],
):
    participant_ids, team_ids = _validate_access_targets(
        db, participant_ids, team_ids
    )

    for user_id in participant_ids:
        db.add(MeetingParticipant(meeting_id=meeting_id, user_id=user_id))
    for team_id in team_ids:
        db.add(MeetingTeam(meeting_id=meeting_id, team_id=team_id))


def _employee_meeting_filter(user_id: int):
    direct_access = exists().where(
        MeetingParticipant.meeting_id == Meeting.id,
        MeetingParticipant.user_id == user_id,
    )
    team_access = exists().where(
        MeetingTeam.meeting_id == Meeting.id,
        MeetingTeam.team_id == TeamMember.team_id,
        TeamMember.user_id == user_id,
    )
    return or_(direct_access, team_access)


def check_meeting_access(
    meeting_id: int,
    current_user: User,
    db: Session,
):
    # Admins can access every meeting.
    if current_user.role == "admin":
        return

    direct = db.scalar(
        select(MeetingParticipant.id).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == current_user.id,
        )
    )
    team = db.scalar(
        select(MeetingTeam.id)
        .join(TeamMember, TeamMember.team_id == MeetingTeam.team_id)
        .where(
            MeetingTeam.meeting_id == meeting_id,
            TeamMember.user_id == current_user.id,
        )
    )

    if not direct and not team:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this meeting.",
        )

@router.post("/{meeting_id}/reprocess", response_model=MeetingResponse)
@serialized_write
def reprocess_meeting(
    meeting_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Manually re-trigger the processing pipeline for a meeting that is
    stuck in "processing" (e.g. the server restarted mid-task, or a
    background task died without updating status) or that ended in
    "processing_failed". Safe to call on a "ready" meeting too — it
    will simply regenerate everything from the existing transcript.
    """

    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not meeting.transcript and not meeting.recording_path:
        raise HTTPException(
            status_code=400,
            detail="This meeting has no transcript or recording to process.",
        )

    meeting.status = "processing"
    meeting.processing_error = None
    db.commit()
    db.refresh(meeting)

    background_tasks.add_task(process_meeting_background, meeting.id)

    return meeting


class MeetingUpdate(BaseModel):
    title: str
    meeting_date: datetime
    duration_minutes: int | None = None


@router.post(
    "/",
    response_model=MeetingResponse,
)
def create_meeting(
    meeting_data: MeetingCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Create a meeting.

    If a transcript is provided, automatically start
    the complete meeting-processing pipeline.
    """

    transcript = (
        meeting_data.transcript.strip()
        if meeting_data.transcript
        else None
    )
    if not transcript:
        raise HTTPException(400, "A transcript is required to save a meeting. Use the recording studio for a live session.")

    meeting = Meeting(
        title=meeting_data.title,
        meeting_date=meeting_data.meeting_date,
        duration_minutes=meeting_data.duration_minutes,
        transcript=transcript,
        organizer_id=current_user.id,
        status="processing" if transcript else "uploaded",
    )

    db.add(meeting)
    db.flush()

    _apply_meeting_access(
        db,
        meeting.id,
        meeting_data.participant_ids,
        meeting_data.team_ids,
    )

    db.commit()
    db.refresh(meeting)

    # Automatically process meeting when transcript exists
    if transcript:

        background_tasks.add_task(
            process_meeting_background,
            meeting.id,
        )

    return meeting


@router.put(
    "/{meeting_id}",
    response_model=MeetingResponse,
)
def update_meeting(
    meeting_id: int,
    meeting_data: MeetingUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    meeting.title = meeting_data.title
    meeting.meeting_date = meeting_data.meeting_date
    meeting.duration_minutes = meeting_data.duration_minutes

    db.commit()
    db.refresh(meeting)

    return meeting

@router.delete("/{meeting_id}")
@serialized_write
def delete_meeting(
    meeting_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Delete a meeting and all related data.

    Deletes:
    - ChromaDB embeddings
    - Transcript chunks
    - Meeting participants
    - Meeting record
    """

    # ==========================================
    # FIND MEETING
    # ==========================================

    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    try:

        # ======================================
        # 1. DELETE CHROMADB EMBEDDINGS
        # ======================================

        try:
            delete_chunks(meeting_id)
        except Exception as error:
            print(
                f"[WARNING] Failed to delete embeddings "
                f"for meeting {meeting_id}: {error}"
            )


        # ======================================
        # 2. DELETE TRANSCRIPT CHUNKS
        # ======================================

        db.query(TranscriptChunk).filter(
            TranscriptChunk.meeting_id == meeting_id
        ).delete(
            synchronize_session=False
        )


        # ======================================
        # 3. DELETE MEETING PARTICIPANTS
        # ======================================

        db.query(MeetingParticipant).filter(
            MeetingParticipant.meeting_id == meeting_id
        ).delete(
            synchronize_session=False
        )

        db.query(MeetingTeam).filter(
            MeetingTeam.meeting_id == meeting_id
        ).delete(
            synchronize_session=False
        )


        # ======================================
        # 4. DELETE CHAT MESSAGES
        # ======================================

        db.query(ChatMessage).filter(
            ChatMessage.meeting_id == meeting_id
        ).delete(
            synchronize_session=False
        )


        # ======================================
        # 5. DELETE MEETING
        # ======================================

        db.query(Notification).filter_by(meeting_id=meeting_id).delete(synchronize_session=False)
        recording_path = meeting.recording_path
        db.delete(meeting)

        db.commit()
        if recording_path:
            from pathlib import Path
            from app.config import settings
            path = Path(recording_path).resolve()
            if path.is_relative_to((Path(settings.data_dir) / "recordings").resolve()):
                path.unlink(missing_ok=True)

        # ======================================
        # SUCCESS
        # ======================================

        return {
            "message": "Meeting deleted successfully",
            "meeting_id": meeting_id,
        }


    except Exception as error:

        # ======================================
        # ROLLBACK DATABASE CHANGES
        # ======================================

        db.rollback()

        print(
            f"[ERROR] Failed to delete meeting "
            f"{meeting_id}: {error}"
        )

        raise HTTPException(
            status_code=500,
            detail="Could not delete meeting.",
        )

@router.post(
    "/{meeting_id}/participants",
    response_model=MeetingParticipantResponse,
)
def add_meeting_participant(
    meeting_id: int,
    participant_data: MeetingParticipantCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    # Check meeting exists
    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    # Check user exists
    employee = db.get(User, participant_data.user_id)

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    # Only employees should be assigned through this endpoint
    if employee.role != "employee":
        raise HTTPException(
            status_code=400,
            detail="Only employees can be assigned to meetings.",
        )

    # Prevent duplicate assignment
    existing_participant = db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == participant_data.user_id,
        )
    )

    if existing_participant:
        raise HTTPException(
            status_code=400,
            detail="Employee is already assigned to this meeting.",
        )

    participant = MeetingParticipant(
        meeting_id=meeting_id,
        user_id=participant_data.user_id,
    )

    db.add(participant)
    db.commit()
    db.refresh(participant)

    return participant

@router.get(
    "/{meeting_id}/participants",
    response_model=list[MeetingParticipantResponse],
)
def get_meeting_participants(
    meeting_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    participants = (
        db.query(MeetingParticipant)
        .filter(
            MeetingParticipant.meeting_id == meeting_id
        )
        .all()
    )

    return participants

@router.delete(
    "/{meeting_id}/participants/{user_id}",
)
def remove_meeting_participant(
    meeting_id: int,
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    participant = db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == user_id,
        )
    )

    if participant is None:
        raise HTTPException(
            status_code=404,
            detail="Employee is not assigned to this meeting.",
        )

    db.delete(participant)
    db.commit()

    return {
        "message": "Employee removed from meeting successfully.",
        "meeting_id": meeting_id,
        "user_id": user_id,
    }


@router.get("/{meeting_id}/teams")
def get_meeting_teams(
    meeting_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not db.get(Meeting, meeting_id):
        raise HTTPException(404, "Meeting not found")
    rows = (
        db.query(MeetingTeam, Team)
        .join(Team, Team.id == MeetingTeam.team_id)
        .filter(MeetingTeam.meeting_id == meeting_id)
        .order_by(Team.name)
        .all()
    )
    return [
        {
            "id": link.id,
            "meeting_id": link.meeting_id,
            "team_id": team.id,
            "team": {"id": team.id, "name": team.name},
        }
        for link, team in rows
    ]


@router.post("/{meeting_id}/teams/{team_id}")
def add_meeting_team(
    meeting_id: int,
    team_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not db.get(Meeting, meeting_id):
        raise HTTPException(404, "Meeting not found")
    if not db.get(Team, team_id):
        raise HTTPException(404, "Team not found")
    existing = db.scalar(
        select(MeetingTeam).where(
            MeetingTeam.meeting_id == meeting_id,
            MeetingTeam.team_id == team_id,
        )
    )
    if existing:
        raise HTTPException(400, "Team already has access to this meeting.")
    link = MeetingTeam(meeting_id=meeting_id, team_id=team_id)
    db.add(link)
    db.commit()
    return {"message": "Team assigned successfully.", "team_id": team_id}


@router.delete("/{meeting_id}/teams/{team_id}")
def remove_meeting_team(
    meeting_id: int,
    team_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    link = db.scalar(
        select(MeetingTeam).where(
            MeetingTeam.meeting_id == meeting_id,
            MeetingTeam.team_id == team_id,
        )
    )
    if not link:
        raise HTTPException(404, "Team is not assigned to this meeting.")
    db.delete(link)
    db.commit()
    return {"message": "Team removed from meeting.", "team_id": team_id}


@router.get(
    "/",
    response_model=list[MeetingResponse],
)
def get_meetings(
    q: str | None = None,
    status_filter: str | None = None,
    sort: str = "newest",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List meetings visible to the current user.

    q            - search meeting titles (and transcript text)
    status_filter - "uploaded" | "processing" | "ready" | "processing_failed"
    sort         - "newest" | "oldest" | "title"
    """

    query = db.query(Meeting)

    # Admins see every meeting; employees only see meetings they are
    # explicitly assigned to (Phase 3 access control).
    if current_user.role != "admin":
        query = query.filter(_employee_meeting_filter(current_user.id))

    if status_filter:
        query = query.filter(Meeting.status == status_filter)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Meeting.title.ilike(like), Meeting.transcript.ilike(like))
        )

    if sort == "oldest":
        query = query.order_by(Meeting.created_at.asc())
    elif sort == "title":
        query = query.order_by(Meeting.title.asc())
    else:
        query = query.order_by(Meeting.created_at.desc())

    return query.all()


@router.get("/stats/overview", response_model=MeetingStats)
def get_meeting_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Aggregate counts for the admin / employee dashboards (Phase 10/11)."""

    query = db.query(Meeting)

    if current_user.role != "admin":
        query = query.filter(_employee_meeting_filter(current_user.id))

    meetings = query.all()

    stats = {
        "total": len(meetings),
        "uploaded": 0,
        "processing": 0,
        "ready": 0,
        "processing_failed": 0,
    }

    for meeting in meetings:
        if meeting.status in stats:
            stats[meeting.status] += 1

    return stats


@router.get(
    "/{meeting_id}",
    response_model=MeetingResponse,
)
def get_meeting(
    meeting_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    # Check whether this user is allowed to access the meeting
    check_meeting_access(
        meeting_id=meeting_id,
        current_user=current_user,
        db=db,
    )

    return meeting

@router.put(
    "/{meeting_id}/transcript",
    response_model=MeetingResponse,
)
@serialized_write
def update_transcript(
    meeting_id: int,
    transcript_data: TranscriptUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    new_transcript = transcript_data.transcript.strip()

    if not new_transcript:
        raise HTTPException(
            status_code=400,
            detail="Transcript cannot be empty.",
        )

    # Save transcript
    meeting.transcript = new_transcript
    db.query(TranscriptChunk).filter_by(meeting_id=meeting_id).delete(synchronize_session=False)
    meeting.summary = None
    meeting.action_items = None
    meeting.processing_error = None
    db.query(ChatMessage).filter_by(meeting_id=meeting_id).delete(synchronize_session=False)

    # Tell frontend that processing has started
    meeting.status = "processing"




    db.commit()
    db.refresh(meeting)


    # ==========================================
    # AUTOMATIC PROCESSING
    # ==========================================

    background_tasks.add_task(
        process_meeting_background,
        meeting.id,
    )


    return meeting

@router.post(
    "/{meeting_id}/process-transcript",
)
@serialized_write
def process_transcript(
    meeting_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    if not meeting.transcript:
        raise HTTPException(
            status_code=400,
            detail="Meeting does not have a transcript",
        )

    # Remove existing chunks so processing is safe to repeat
    db.query(TranscriptChunk).filter(
        TranscriptChunk.meeting_id == meeting_id
    ).delete()

    chunks = chunk_transcript(meeting.transcript)

    for index, content in enumerate(chunks):
        chunk = TranscriptChunk(
            meeting_id=meeting.id,
            chunk_index=index,
            content=content,
        )

        db.add(chunk)

    meeting.status = "chunked"

    db.commit()

    return {
        "message": "Transcript processed successfully",
        "meeting_id": meeting.id,
        "chunks_created": len(chunks),
        "status": meeting.status,
    }


@router.post(
    "/{meeting_id}/create-embeddings",
)
@serialized_write
def create_meeting_embeddings(
    meeting_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    chunks = (
        db.query(TranscriptChunk)
        .filter(TranscriptChunk.meeting_id == meeting_id)
        .order_by(TranscriptChunk.chunk_index)
        .all()
    )

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No transcript chunks found. Process the transcript first.",
        )

    delete_chunks(meeting_id)

    ids = []
    documents = []
    embeddings = []
    metadatas = []

    for chunk in chunks:
        embedding = create_embedding(chunk.content)

        ids.append(f"meeting_{meeting_id}_chunk_{chunk.chunk_index}")
        documents.append(chunk.content)
        embeddings.append(embedding)

        metadatas.append({
            "meeting_id": meeting_id,
            "chunk_id": chunk.id,
            "chunk_index": chunk.chunk_index,
        })

    add_chunks(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    meeting.status = "embedded"

    db.commit()

    return {
        "message": "Embeddings created successfully",
        "meeting_id": meeting_id,
        "chunks_embedded": len(chunks),
        "status": meeting.status,
    }

class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be empty")
        return value.strip()

@router.post("/{meeting_id}/search")
def search_meeting(
    meeting_id: int,
    request: SearchRequest,
    current_user: User = Depends(require_role("admin")),
):
    query_embedding = create_embedding(request.question)

    results, _space = search(
        query_embedding=query_embedding,
        meeting_id=meeting_id,
        n_results=5,
    )

    return {
        "meeting_id": meeting_id,
        "question": request.question,
        "results": results["documents"][0],
    }

@router.post("/{meeting_id}/ask")
def ask_meeting(
    meeting_id: int,
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    check_meeting_access(
    meeting_id=meeting_id,
    current_user=current_user,
    db=db,
    )

    from app.services.retrieval import retrieve
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status == "processing":
        raise HTTPException(status_code=409, detail="Meeting is processing. Chat will update automatically when ready.")
    history_messages = list(db.scalars(
        select(ChatMessage).where(ChatMessage.meeting_id == meeting_id, ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(10)
    ).all())
    chat_history = [{"role": m.role, "content": m.content} for m in reversed(history_messages)]
    resolved_question = resolve_followup_question(request.question, chat_history)
    documents = []
    try:
        results, _ = search(create_embedding(resolved_question), meeting_id, n_results=8)
        documents = results.get("documents", [[]])[0]
    except Exception:
        # A missing/stale index or unavailable embedding provider never hides SQL evidence.
        pass
    sources = retrieve(db, meeting, resolved_question, documents)
    context = "\n\n".join(f"[{s['label']}]\n{s['content']}" for s in sources)
    # A search rewrite can expand context; the answer must follow the original scope.
    answer = generate_answer(request.question, context, chat_history) if context else "I couldn't find a transcript for this meeting."
    db.add_all([
        ChatMessage(meeting_id=meeting_id, user_id=current_user.id, role="user", content=request.question),
        ChatMessage(meeting_id=meeting_id, user_id=current_user.id, role="assistant", content=answer,
                    sources_json=json.dumps(sources, ensure_ascii=False)),
    ])
    db.commit()
    return {"meeting_id": meeting_id, "question": request.question, "answer": answer, "sources": sources}


@router.post("/webhook-test")
def webhook_test(data: dict):
    print("✅ WEBHOOK DATA RECEIVED:")
    print(data)

    return {
        "success": True,
        "message": "Webhook received successfully",
        "received_data": data,
    }

@router.post("/{meeting_id}/generate-summary")
@serialized_write
def generate_meeting_summary(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    # Find meeting
    meeting = db.get(Meeting, meeting_id)

    if not meeting:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    # Make sure transcript exists
    if not meeting.transcript:
        raise HTTPException(
            status_code=400,
            detail="Meeting does not have a transcript",
        )

    if meeting.summary:
        return {
            "meeting_id": meeting.id,
            "summary": meeting.summary,
            "action_items": json.loads(meeting.action_items or "[]"),
            "status": meeting.status,
            "message": "Summary already exists",
        }

    # Generate structured summary + action items
    structured = generate_structured_summary(
        transcript=meeting.transcript,
    )

    # Save summary
    meeting.summary = structured_summary_to_text(structured)
    meeting.action_items = json.dumps(structured.get("action_items", []))
    meeting.status = "processed"

    db.commit()
    db.refresh(meeting)

    return {
        "meeting_id": meeting.id,
        "summary": meeting.summary,
        "action_items": structured.get("action_items", []),
        "status": meeting.status,
    }

@router.get("/{meeting_id}/chat-debug")
def chat_debug(

    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_meeting_access(
        meeting_id=meeting_id,
        current_user=current_user,
        db=db,
    )

    messages = db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.meeting_id == meeting_id,
            ChatMessage.user_id == current_user.id,
        )
        .order_by(ChatMessage.created_at)
    ).all()

    return {
        "current_user": {
            "id": current_user.id,
            "email": current_user.email,
            "role": current_user.role,
        },
        "messages": [
            {
                "id": message.id,
                "user_id": message.user_id,
                "role": message.role,
                "content": message.content,
                "sources": json.loads(message.sources_json or "[]"),
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }
