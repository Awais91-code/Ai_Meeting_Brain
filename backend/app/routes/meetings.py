from fastapi import APIRouter, Depends,HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Meeting, User,TranscriptChunk
from app.schemas.meeting import MeetingCreate, MeetingResponse
from app.security.auth import (
    get_current_user,
    require_role,
)
from app.schemas.transcript import TranscriptUpdate
from app.services.transcript import chunk_transcript
from app.services.embeddings import create_embedding
from app.services.vector_store import add_chunks,search
from pydantic import BaseModel
from app.services.llm import generate_answer, resolve_followup_question
from sqlalchemy import select
from app.models.chat_message import ChatMessage
from app.services.summary import generate_summary
from app.models.meeting_participant import MeetingParticipant
from app.schemas.meeting_participant import (
    MeetingParticipantCreate,
    MeetingParticipantResponse,
)



router = APIRouter(
    prefix="/meetings",
    tags=["Meetings"],
)

def check_meeting_access(
    meeting_id: int,
    current_user: User,
    db: Session,
):
    # Admins can access every meeting
    if current_user.role == "admin":
        return

    # Check whether the employee is explicitly assigned
    participant = db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == current_user.id,
        )
    )

    if not participant:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this meeting.",
        )


@router.post(
    "/",
    response_model=MeetingResponse,
)
def create_meeting(
    meeting_data: MeetingCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    meeting = Meeting(
        title=meeting_data.title,
        meeting_date=meeting_data.meeting_date,
        duration_minutes=meeting_data.duration_minutes,
        transcript=meeting_data.transcript,
        organizer_id=current_user.id,
    )

    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    return meeting

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


@router.get(
    "/",
    response_model=list[MeetingResponse],
)
def get_meetings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Admins can see all meetings
    if current_user.role == "admin":
        meetings = (
            db.query(Meeting)
            .order_by(Meeting.meeting_date.desc())
            .all()
        )

        return meetings

    # Employees can only see meetings they are assigned to
    meetings = (
        db.query(Meeting)
        .join(
            MeetingParticipant,
            MeetingParticipant.meeting_id == Meeting.id,
        )
        .filter(
            MeetingParticipant.user_id == current_user.id
        )
        .order_by(Meeting.meeting_date.desc())
        .all()
    )

    return meetings


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
def update_transcript(
    meeting_id: int,
    transcript_data: TranscriptUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    meeting = db.get(Meeting, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=404,
            detail="Meeting not found",
        )

    meeting.transcript = transcript_data.transcript
    meeting.status = "transcript_uploaded"

    db.commit()
    db.refresh(meeting)

    return meeting



@router.post(
    "/{meeting_id}/process-transcript",
)
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
    question: str


@router.post("/{meeting_id}/search")
def search_meeting(
    meeting_id: int,
    request: SearchRequest,
    current_user: User = Depends(require_role("admin")),
):
    query_embedding = create_embedding(request.question)

    results = search(
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

    print("========== AUTH DEBUG ==========")
    print("User ID:", current_user.id)
    print("Email:", current_user.email)
    print("Role:", current_user.role)
    print("Meeting ID:", meeting_id)
    print("================================")

    # 1. Load previous chat history for THIS user and THIS meeting
    history_messages = db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.meeting_id == meeting_id,
            ChatMessage.user_id == current_user.id,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(10)
    ).all()

    history_messages.reverse()

    chat_history = [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in history_messages
    ]

    # 2. Resolve follow-up question
    resolved_question = resolve_followup_question(
        question=request.question,
        chat_history=chat_history,
    )

    print("========== QUESTION DEBUG ==========")
    print("Original question:", request.question)
    print("Resolved question:", resolved_question)
    print("====================================")

    # 3. Create embedding using resolved question
    query_embedding = create_embedding(resolved_question)

    # 4. Search relevant transcript chunks
    results = search(
        query_embedding=query_embedding,
        meeting_id=meeting_id,
        n_results=3,
    )

    documents = results.get("documents", [[]])[0]
    print("========== RETRIEVAL DEBUG ==========")
    print("Question used for search:", resolved_question)

    for i, doc in enumerate(documents, 1):
        print(f"\n--- CHUNK {i} ---")
        print(doc)

    print("=====================================")

    if not documents:
        answer = "I couldn't find relevant information in the meeting transcript."
    else:
        # 5. Build transcript context
        context = "\n\n".join(documents)

        # 6. Generate answer
        answer = generate_answer(
            question=resolved_question,
            context=context,
            chat_history=chat_history,
        )

    # 7. Save ORIGINAL user's question
    user_message = ChatMessage(
        meeting_id=meeting_id,
        user_id=current_user.id,
        role="user",
        content=request.question,
    )

    db.add(user_message)

    # 8. Save AI answer
    assistant_message = ChatMessage(
        meeting_id=meeting_id,
        user_id=current_user.id,
        role="assistant",
        content=answer,
    )

    db.add(assistant_message)

    db.commit()

    return {
        "meeting_id": meeting_id,
        "question": request.question,
        "answer": answer,
    }

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
            "status": meeting.status,
            "message": "Summary already exists",
        }

    # Generate summary
    summary = generate_summary(
        transcript=meeting.transcript,
    )

    # Save summary
    meeting.summary = summary
    meeting.status = "processed"

    db.commit()
    db.refresh(meeting)

    return {
        "meeting_id": meeting.id,
        "summary": meeting.summary,
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
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }