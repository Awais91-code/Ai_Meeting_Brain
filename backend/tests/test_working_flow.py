import io
import json
from pathlib import Path
import pytest
from app.config import settings
from app.database import SessionLocal
from app.models import Meeting, TranscriptChunk
from .conftest import signup_and_login, make_admin


@pytest.fixture
def admin(client, test_engine):
    token = signup_and_login(client, "Capture Admin", "capture@example.com", "test-password-123")
    make_admin(test_engine, "capture@example.com")
    return {"Authorization": f"Bearer {token}"}


def create(client, admin, transcript="The release is Friday."):
    result = client.post('/api/meetings/', headers=admin, json={
        'title': 'Planning', 'meeting_date': '2026-09-16T10:00:00Z', 'transcript': transcript})
    assert result.status_code == 200, result.text
    return result.json()['id']


def test_recording_saved_transcribed_and_answerable(client, admin, monkeypatch):
    from app.services import transcription, meeting_processor, embeddings, vector_store, summary
    # Exercise the real CPU lexical vectors, Chroma, SQL and grounded answer path.
    monkeypatch.setattr(meeting_processor, 'create_embedding', embeddings.create_embedding)
    monkeypatch.setattr(meeting_processor, 'add_chunks', vector_store.add_chunks)
    monkeypatch.setattr(meeting_processor, 'delete_chunks', vector_store.delete_chunks)
    monkeypatch.setattr(meeting_processor, 'generate_structured_summary', summary.generate_structured_summary)
    calls = []
    def transcribe(path, **kwargs):
        assert Path(path).read_bytes() == b'recorded-audio'
        calls.append(path)
        return 'Ayesha: The release deadline is Friday. Omar will test the payment gateway.'
    monkeypatch.setattr(transcription, 'transcribe_audio', transcribe)
    result = client.post('/api/capture/', headers=admin, json={'title':'Live planning'})
    assert result.status_code == 200
    session_id = result.json()['session_id']
    with SessionLocal() as db:
        assert db.query(Meeting).count() == 0
    result = client.post(f'/api/live/{session_id}/audio', headers=admin,
                         files={'audio':('meeting.webm', b'recorded-audio', 'audio/webm')})
    assert result.status_code == 200, result.text
    meeting_id = client.get(f'/api/live/{session_id}', headers=admin).json()['meeting_id']
    current = client.get(f'/api/meetings/{meeting_id}', headers=admin).json()
    assert current['status'] == 'ready'
    assert 'Friday' in current['transcript']
    answer = client.post(f'/api/meetings/{meeting_id}/ask', headers=admin,
                         json={'question':'What is the release deadline?'}).json()
    assert 'Friday' in answer['answer']
    assert 'AI generation is unavailable' in answer['answer']
    assert answer['sources'][0]['meeting_id'] == meeting_id
    history = client.get(f'/api/meetings/{meeting_id}/chat-debug', headers=admin).json()
    assert history['messages'][-1]['sources'] == answer['sources']
    again = client.post(f'/api/live/{session_id}/audio', headers=admin,
                        files={'audio':('meeting.webm', b'recorded-audio', 'audio/webm')})
    assert again.status_code == 200
    assert len(calls) == 1


def test_restart_recovers_committed_pending_meeting(client, admin, monkeypatch):
    from app.routes import meetings
    from app.services.worker import process_pending_meeting
    monkeypatch.setattr(meetings, 'process_meeting_background', lambda _: None)
    meeting_id = create(client, admin, 'Omar: We approved the release for Monday.')
    with SessionLocal() as db:
        assert db.get(Meeting, meeting_id).status == 'processing'
    process_pending_meeting(meeting_id)
    with SessionLocal() as db:
        assert db.get(Meeting, meeting_id).status == 'ready'
        assert db.query(TranscriptChunk).filter_by(meeting_id=meeting_id).count() > 0


def test_new_transcript_replaces_chat_evidence(client, admin):
    meeting_id = create(client, admin, 'The release deadline is Monday.')
    result = client.put(f'/api/meetings/{meeting_id}/transcript', headers=admin,
                        json={'transcript':'The release deadline changed to Friday.'})
    assert result.status_code == 200
    response = client.post(f'/api/meetings/{meeting_id}/ask', headers=admin, json={'question':'What is the release deadline?'})
    assert response.status_code == 200
    assert 'Friday' in response.json()['answer']
    assert 'Monday' not in str(response.json()['sources'])


def test_vector_outage_does_not_break_chat(client, admin, monkeypatch):
    from app.routes import meetings
    meeting_id = create(client, admin, 'The database migration is assigned to Sana.')
    monkeypatch.setattr(meetings, 'create_embedding', lambda _: (_ for _ in ()).throw(RuntimeError('offline')))
    result = client.post(f'/api/meetings/{meeting_id}/ask', headers=admin,
                        json={'question':'Who owns the database migration?'})
    assert result.status_code == 200
    assert 'Sana' in result.json()['answer']


def test_vector_failure_keeps_sql_ready(client, admin, monkeypatch):
    from app.services import meeting_processor
    monkeypatch.setattr(meeting_processor, 'create_embedding', lambda _: (_ for _ in ()).throw(RuntimeError('offline')))
    meeting_id = create(client, admin, 'The release is Friday.')
    result = client.get(f'/api/meetings/{meeting_id}', headers=admin).json()
    assert result['status'] == 'ready'
    assert 'index unavailable' in result['processing_error']


def test_failed_transcription_can_retry_saved_audio(client, admin, monkeypatch):
    from app.services import transcription
    monkeypatch.setattr(transcription, 'transcribe_audio', lambda *a, **k: (_ for _ in ()).throw(ValueError('No speech')))
    session_id = client.post('/api/live/', headers=admin, json={'title':'Retry audio'}).json()['session_id']
    client.post(f'/api/live/{session_id}/audio', headers=admin, files={'audio':('audio.wav', b'speech')})
    assert client.get(f'/api/live/{session_id}', headers=admin).json()['status'] == 'processing_failed'
    with SessionLocal() as db:
        assert db.query(Meeting).count() == 0
    monkeypatch.setattr(transcription, 'transcribe_audio', lambda *a, **k: 'The release is Friday.')
    assert client.post(f'/api/live/{session_id}/retry', headers=admin).status_code == 200
    assert client.get(f'/api/live/{session_id}', headers=admin).json()['status'] == 'ready'


@pytest.mark.parametrize('question', ['', '   ', 'x'*2001])
def test_invalid_questions_rejected(client, admin, question):
    meeting_id = create(client, admin)
    assert client.post(f'/api/meetings/{meeting_id}/ask', headers=admin,
                       json={'question':question}).status_code == 422


def test_employee_cannot_capture_or_read_unassigned(client, admin):
    meeting_id = create(client, admin, 'Private release details.')
    token = signup_and_login(client, 'Employee', 'reader@example.com', 'password-123')
    headers = {'Authorization':f'Bearer {token}'}
    assert client.get(f'/api/capture/{meeting_id}', headers=headers).status_code == 403
    assert client.post(f'/api/capture/{meeting_id}/audio', headers=headers, files={'audio':('a.wav', b'a')}).status_code == 403
    assert client.post(f'/api/meetings/{meeting_id}/ask', headers=headers, json={'question':'release?'}).status_code == 403


def test_webhook_is_idempotent(client, admin, monkeypatch):
    monkeypatch.setattr(settings, 'n8n_webhook_secret', 'secret')
    data = {'title':'Webhook meeting', 'meeting_date':'2026-09-16T10:00:00Z',
            'transcript':'Launch is Friday.', 'organizer_email':'capture@example.com',
            'source':'meet', 'external_id':'external-meeting-123'}
    first = client.post('/api/webhooks/n8n/meetings', json=data, headers={'X-Webhook-Secret':'secret'})
    second = client.post('/api/webhooks/n8n/meetings', json=data, headers={'X-Webhook-Secret':'secret'})
    assert first.status_code == second.status_code == 200
    assert first.json()['meeting_id'] == second.json()['meeting_id']
    assert second.json()['duplicate']


def test_processing_blocks_concurrent_edit(client, admin):
    from app.services.worker import meeting_lock
    meeting_id = create(client, admin, 'Existing transcript.')
    with meeting_lock(meeting_id):
        response = client.put(f'/api/meetings/{meeting_id}/transcript', headers=admin,
                              json={'transcript':'Replacement transcript.'})
    assert response.status_code == 409


def test_unrelated_question_does_not_invent_answer():
    from app.services.llm import generate_answer
    assert "couldn't find" in generate_answer('What is the population of Jupiter?', 'The release deadline is Friday.')


def test_long_speaker_turn_is_bounded():
    from app.services.transcript import chunk_transcript
    words = [f'word{i}' for i in range(1000)]
    chunks = chunk_transcript('Speaker: ' + ' '.join(words))
    assert max(len(c.split()) for c in chunks) <= 300
    assert set(words).issubset(set(' '.join(chunks).split()))


def test_summary_parses_provider_prose_and_rejects_scalar_lists():
    from app.services.summary import _parse_structured_response
    result = _parse_structured_response('Here are the notes: {"overview":"Release planning", "key_points":"Friday", "action_items":[]}', 'Release planning')
    assert result['overview'] == 'Release planning'
    assert result['key_points'] == []


def test_active_recording_session_can_refresh(client, admin):
    result = client.post('/users/refresh', headers=admin)
    assert result.status_code == 200
    assert client.get('/users/me', headers={'Authorization':'Bearer '+result.json()['access_token']}).status_code == 200


def test_audio_limits_and_empty_upload(client, admin, monkeypatch):
    monkeypatch.setattr(settings, 'max_audio_mb', 1)
    session_id = client.post('/api/live/', headers=admin, json={'title':'Limits'}).json()['session_id']
    for payload, status in [(b'',400), (b'x'*(1024*1024+1),413)]:
        result = client.post(f'/api/live/{session_id}/audio', headers=admin, files={'audio':('audio.wav',payload)})
        assert result.status_code == status
    with SessionLocal() as db:
        assert db.query(Meeting).count() == 0
    assert client.get(f'/api/live/{session_id}', headers=admin).json()['status'] == 'draft'
