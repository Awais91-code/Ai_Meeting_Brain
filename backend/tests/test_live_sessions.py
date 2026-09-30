from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import jwt
import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Meeting, MeetingParticipant, User
from app.services import live_sessions, transcription
from .conftest import signup_and_login


@pytest.fixture
def people(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "jitsi_domain", "meet.example.test")
    monkeypatch.setattr(settings, "jitsi_app_secret", "private-conference-secret-for-tests-123456789")
    monkeypatch.setattr(settings, "jitsi_require_auth", True)
    result = []
    for name, role in [("Host", "admin"), ("Attendee", "employee"), ("Other", "employee")]:
        token = signup_and_login(client, name, name.lower()+"@example.com", "test-password-123", role)
        result.append({"Authorization": "Bearer " + token})
    return result


def draft(client, host, **kwargs):
    result = client.post("/api/live/", headers=host, json={"title":"Team meeting", **kwargs})
    assert result.status_code == 200, result.text
    return result.json()["session_id"]


def test_only_admin_can_provision_employees(client, people):
    host, attendee, _ = people
    payload = {"name":"Outsider", "email":"outsider@example.com", "password":"password-123"}
    assert client.post("/users/", json=payload).status_code in (401, 403)
    assert client.post("/users/", json=payload, headers=attendee).status_code == 403
    assert client.post("/users/", json=payload, headers=host).status_code == 200


def test_title_only_does_not_create_meeting(client, people):
    host, _, _ = people
    draft(client, host)
    assert client.post("/api/meetings/", headers=host, json={"title":"Only title", "meeting_date":"2026-09-16T10:00:00Z"}).status_code == 400
    assert client.post("/api/capture/", headers=host, json={"title":"Legacy create"}).json()["session_id"]
    with SessionLocal() as db:
        assert db.query(Meeting).count() == 0


def test_account_with_pending_attendance_is_preserved_on_delete(client, people):
    host, attendee, _ = people
    session_id = draft(client, host)
    receipt = client.post(f"/api/live/{session_id}/admission", headers=attendee).json()["receipt"]
    client.post(f"/api/live/{session_id}/joined", headers=attendee, json={"receipt":receipt})
    user_id = client.get("/users/me", headers=attendee).json()["id"]
    result = client.delete(f"/users/{user_id}", headers=host)
    assert result.status_code == 200 and result.json()["deactivated"]
    with SessionLocal() as db:
        assert db.get(User, user_id) is not None
        assert not db.get(User, user_id).is_active


def test_employee_joins_then_automatically_gets_saved_notes(client, people, monkeypatch):
    host, attendee, other = people
    session_id = draft(client, host, language="ur")
    assert client.post(f"/api/live/{session_id}/admission").status_code in (401,403)
    ticket_response = client.post(f"/api/live/{session_id}/admission", headers=attendee)
    assert ticket_response.headers["cache-control"] == "no-store"
    ticket = ticket_response.json()
    claims = jwt.decode(ticket["jwt"], settings.jitsi_app_secret, algorithms=["HS256"], audience=settings.jitsi_app_id)
    assert claims["room"] == live_sessions.read_session(session_id)["room"] != "*"
    assert claims["exp"] - claims["iat"] == 300
    assert client.post(f"/api/live/{session_id}/joined", headers=other, json={"receipt":ticket["receipt"]}).status_code == 403
    assert client.post(f"/api/live/{session_id}/joined", headers=attendee, json={"receipt":ticket["receipt"]}).status_code == 200
    def transcribe(path, language, vocabulary):
        with SessionLocal() as db:
            assert db.query(Meeting).count() == 0  # No placeholder during inference.
        assert language == "ur"
        return "[00:00] منصوبے کا بجٹ پچاس ہزار روپے ہے۔"
    monkeypatch.setattr(transcription, "transcribe_audio", transcribe)
    endpoint = f"/api/live/{session_id}/audio"
    assert client.post(endpoint, headers=attendee, files={"audio":("m.wav", b"audio")}).status_code == 403
    assert client.post(endpoint, headers=host, files={"audio":("m.wav", b"audio")}).status_code == 200
    data = client.get(f"/api/live/{session_id}", headers=attendee).json()
    assert data["status"] == "ready"
    meeting_id = data["meeting_id"]
    assert client.get(f"/api/meetings/{meeting_id}", headers=attendee).status_code == 200
    assert client.get(f"/api/meetings/{meeting_id}", headers=other).status_code == 403
    assert client.get(f"/api/live/{session_id}", headers=other).status_code == 403
    assert client.post(f"/api/live/{session_id}/admission", headers=other).status_code == 409
    assert client.post(endpoint, headers=host, files={"audio":("m.wav", b"audio")}).status_code == 200
    assert client.post(f"/api/live/{session_id}/joined", headers=attendee, json={"receipt":ticket["receipt"]}).status_code == 200
    with SessionLocal() as db:
        assert db.query(Meeting).count() == 1
        assert db.query(MeetingParticipant).count() == 1


def test_conferencing_fails_closed_and_disabled_users_cannot_join(client, people, monkeypatch):
    host, attendee, _ = people
    session_id = draft(client, host)
    endpoint = f"/api/live/{session_id}/admission"
    monkeypatch.setattr(settings, "jitsi_domain", "meet.jit.si")
    assert client.post(endpoint, headers=attendee).status_code == 503
    monkeypatch.setattr(settings, "jitsi_domain", "private.example.test")
    monkeypatch.setattr(settings, "jitsi_require_auth", False)
    assert client.post(endpoint, headers=attendee).status_code == 503
    monkeypatch.setattr(settings, "jitsi_require_auth", True)
    with SessionLocal() as db:
        db.query(User).filter_by(email="attendee@example.com").first().is_active = False
        db.commit()
    assert client.post(endpoint, headers=attendee).status_code == 401


def test_expired_and_wrong_room_receipts_rejected(client, people):
    host, attendee, _ = people
    first, second = draft(client, host), draft(client, host)
    ticket = client.post(f"/api/live/{first}/admission", headers=attendee).json()
    assert client.post(f"/api/live/{second}/joined", headers=attendee, json={"receipt":ticket["receipt"]}).status_code == 403
    with live_sessions.edit_session(first) as data:
        data["created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert client.post(f"/api/live/{first}/admission", headers=attendee).status_code == 409


def test_restart_and_post_commit_crash_do_not_duplicate_meeting(client, people, monkeypatch):
    host, attendee, _ = people
    session_id = draft(client, host)
    receipt = client.post(f"/api/live/{session_id}/admission", headers=attendee).json()["receipt"]
    real_process = live_sessions.process_session
    monkeypatch.setattr(live_sessions, "process_session", lambda _: None)
    calls = []
    def transcribe(*args, **kwargs):
        calls.append(1)
        return "The budget is 50000 rupees."
    monkeypatch.setattr(transcription, "transcribe_audio", transcribe)
    client.post(f"/api/live/{session_id}/audio", headers=host, files={"audio":("m.wav", b"speech")})
    assert session_id in list(live_sessions.pending_sessions())
    real_process(session_id)
    # Simulate SQL commit succeeding just before a crash lost the manifest update.
    with live_sessions.edit_session(session_id) as data:
        data.update(status="processing", meeting_id=None)
    # The callback can arrive after SQL commit but before manifest recovery.
    assert client.post(f"/api/live/{session_id}/joined", headers=attendee, json={"receipt":receipt}).status_code == 200
    real_process(session_id)
    with SessionLocal() as db:
        assert db.query(Meeting).count() == 1
        assert db.query(MeetingParticipant).count() == 1
    assert len(calls) == 1


def test_failed_silent_audio_can_be_replaced(client, people, monkeypatch):
    host, _, _ = people
    session_id = draft(client, host)
    monkeypatch.setattr(transcription, "transcribe_audio", lambda *a, **k: "")
    client.post(f"/api/live/{session_id}/audio", headers=host, files={"audio":("m.wav", b"silence")})
    with SessionLocal() as db:
        assert db.query(Meeting).count() == 0
    assert live_sessions.read_session(session_id)["status"] == "processing_failed"
    monkeypatch.setattr(transcription, "transcribe_audio", lambda *a, **k: "बजट पचास हजार रुपये है।")
    client.post(f"/api/live/{session_id}/audio", headers=host, files={"audio":("m.wav", b"speech")})
    data = client.get(f"/api/live/{session_id}", headers=host).json()
    assert data["status"] == "ready"
    meeting = client.get(f"/api/meetings/{data['meeting_id']}", headers=host).json()
    assert "पचास" in meeting["transcript"]


@pytest.mark.parametrize("mode", ["auto", "en", "ur", "hi"])
def test_transcription_preserves_language_and_unicode(monkeypatch, mode):
    options = {}
    def transcribe(path, **kwargs):
        options.update(kwargs)
        return iter([SimpleNamespace(start=61, text=" اردو English हिन्दी ")]), None
    monkeypatch.setattr(transcription, "whisper_model", lambda: SimpleNamespace(transcribe=transcribe))
    monkeypatch.setattr(settings, "whisper_model", "small")
    result = transcription.transcribe_audio("recording.wav", language=mode, vocabulary="Zika, Ayesha")
    assert result == "[01:01] اردو English हिन्दी"
    assert options["task"] == "transcribe"
    assert options["language"] == (None if mode == "auto" else mode)
    assert options["multilingual"] == (mode == "auto")
    assert options["hotwords"] == "Zika, Ayesha"
