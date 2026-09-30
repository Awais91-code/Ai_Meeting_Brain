"""Persist input first, build SQL evidence atomically, then publish readiness."""
import json
import logging
from app.models import Meeting, TranscriptChunk
from app.services.transcript import chunk_transcript
from app.services.embeddings import create_embedding
from app.services.vector_store import add_chunks, delete_chunks
from app.services.summary import generate_structured_summary, structured_summary_to_text
from app.services.notifications import notify_meeting_ready

logger = logging.getLogger(__name__)


def process_meeting_automatically(meeting_id, db):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise ValueError("Meeting not found")
    try:
        if not meeting.transcript and meeting.recording_path:
            from app.services.transcription import transcribe_audio
            meeting.transcript = transcribe_audio(meeting.recording_path)
            db.commit()  # Never repeat expensive transcription after a later failure.
        if not meeting.transcript or not meeting.transcript.strip():
            raise ValueError("No speech/transcript found. Check shared-tab audio and microphone.")
        contents = chunk_transcript(meeting.transcript)
        db.query(TranscriptChunk).filter_by(meeting_id=meeting_id).delete(synchronize_session=False)
        chunks = [TranscriptChunk(meeting_id=meeting_id, chunk_index=i, content=text)
                  for i, text in enumerate(contents)]
        db.add_all(chunks)
        db.commit()  # Publish chunks atomically, without holding SQL writes during AI calls.
        warning = None
        try:
            embeddings = [create_embedding(chunk.content) for chunk in chunks]
            delete_chunks(meeting_id)
            add_chunks(ids=[f"meeting_{meeting_id}_chunk_{c.chunk_index}" for c in chunks],
                       documents=contents, embeddings=embeddings,
                       metadatas=[{"meeting_id": meeting_id, "chunk_id": c.id, "chunk_index": c.chunk_index} for c in chunks])
        except Exception as error:
            # SQL chunks are a fully usable retrieval index; retain readiness.
            logger.warning("Vector indexing unavailable for %s (%s)", meeting_id, type(error).__name__)
            warning = "Semantic index unavailable; chat uses saved transcript evidence. Reprocess to retry."
        summary = generate_structured_summary(meeting.transcript)
        meeting.summary = structured_summary_to_text(summary)
        meeting.action_items = json.dumps(summary.get("action_items", []), ensure_ascii=False)
        meeting.status = "ready"
        meeting.processing_error = warning
        db.commit()
        try:
            notify_meeting_ready(meeting, db)
        except Exception:
            db.rollback()
            logger.exception("Notification delivery failed for meeting %s", meeting_id)
        return meeting
    except Exception as error:
        db.rollback()
        meeting = db.get(Meeting, meeting_id)
        if meeting:
            meeting.status = "processing_failed"
            meeting.processing_error = f"{type(error).__name__}: {str(error)[:1200]}"
            db.commit()
        raise
