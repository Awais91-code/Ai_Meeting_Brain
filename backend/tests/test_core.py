from tests.conftest import signup_and_login, make_admin


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# AUTHENTICATION
# ============================================================

def test_signup_and_login(client):
    token = signup_and_login(
        client, "Alice", "alice@example.com", "password123"
    )
    assert token

    me = client.get("/users/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"
    assert me.json()["role"] == "employee"


def test_login_wrong_password_fails(client):
    signup_and_login(client, "Bob", "bob@example.com", "password123")

    response = client.post(
        "/users/login",
        json={"email": "bob@example.com", "password": "wrong"},
    )
    assert response.status_code == 401


def test_disabled_account_cannot_login(client, test_engine):
    signup_and_login(client, "Carl", "carl@example.com", "password123")

    from sqlalchemy.orm import Session
    from app.models import User

    with Session(test_engine) as session:
        user = session.query(User).filter(User.email == "carl@example.com").first()
        user.is_active = False
        session.commit()

    response = client.post(
        "/users/login",
        json={"email": "carl@example.com", "password": "password123"},
    )
    assert response.status_code == 401


def test_unauthenticated_request_rejected(client):
    response = client.get("/users/me")
    assert response.status_code in (401, 403)


# ============================================================
# MEETINGS: CREATE / ACCESS CONTROL
# ============================================================

def test_employee_cannot_create_meeting(client):
    token = signup_and_login(
        client, "Employee1", "emp1@example.com", "password123"
    )

    response = client.post(
        "/api/meetings/",
        json={
            "title": "Sprint planning",
            "meeting_date": "2026-09-01T10:00:00",
            "transcript": "The release is Friday.",
            "duration_minutes": 30,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 403


def test_admin_can_create_meeting(client, test_engine):
    admin_token = signup_and_login(
        client, "Admin", "admin@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin@example.com")

    response = client.post(
        "/api/meetings/",
        json={
            "title": "Sprint planning",
            "meeting_date": "2026-09-01T10:00:00",
            "transcript": "The release is Friday.",
            "duration_minutes": 30,
        },
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Sprint planning"
    assert body["status"] == "processing"
    assert body["action_items"] == []


def test_employee_cannot_access_unassigned_meeting(client, test_engine):
    admin_token = signup_and_login(
        client, "Admin2", "admin2@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin2@example.com")

    meeting_id = client.post(
        "/api/meetings/",
        json={
            "title": "Private meeting",
            "meeting_date": "2026-09-01T10:00:00",
            "transcript": "The release is Friday.",
        },
        headers=auth_headers(admin_token),
    ).json()["id"]

    employee_token = signup_and_login(
        client, "Employee2", "emp2@example.com", "password123"
    )

    # Not assigned -> forbidden, even though the meeting exists.
    response = client.get(
        f"/api/meetings/{meeting_id}", headers=auth_headers(employee_token)
    )
    assert response.status_code == 403

    # Also must not show up in their meeting list.
    listing = client.get(
        "/api/meetings/", headers=auth_headers(employee_token)
    )
    assert listing.status_code == 200
    assert all(m["id"] != meeting_id for m in listing.json())


# ============================================================
# PARTICIPANTS  (Phase 2 / 3 / 16)
# ============================================================

def test_participant_assign_duplicate_and_remove(client, test_engine):
    admin_token = signup_and_login(
        client, "Admin3", "admin3@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin3@example.com")

    employee_token = signup_and_login(
        client, "Employee3", "emp3@example.com", "password123"
    )

    me = client.get("/users/me", headers=auth_headers(employee_token))
    employee_id = me.json()["id"]

    meeting_id = client.post(
        "/api/meetings/",
        json={
            "title": "Team sync",
            "meeting_date": "2026-09-01T10:00:00",
            "transcript": "The release is Friday.",
        },
        headers=auth_headers(admin_token),
    ).json()["id"]

    # Employee cannot self-assign to meetings.
    forbidden = client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"user_id": employee_id},
        headers=auth_headers(employee_token),
    )
    assert forbidden.status_code == 403

    # Admin assigns the employee.
    assign = client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"user_id": employee_id},
        headers=auth_headers(admin_token),
    )
    assert assign.status_code == 200, assign.text
    assert assign.json()["user"]["email"] == "emp3@example.com"

    # Duplicate assignment is rejected.
    duplicate = client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"user_id": employee_id},
        headers=auth_headers(admin_token),
    )
    assert duplicate.status_code == 400

    # Now the employee CAN see the meeting.
    access = client.get(
        f"/api/meetings/{meeting_id}", headers=auth_headers(employee_token)
    )
    assert access.status_code == 200

    # List participants.
    participants = client.get(
        f"/api/meetings/{meeting_id}/participants",
        headers=auth_headers(admin_token),
    )
    assert len(participants.json()) == 1

    # Remove participant.
    removed = client.delete(
        f"/api/meetings/{meeting_id}/participants/{employee_id}",
        headers=auth_headers(admin_token),
    )
    assert removed.status_code == 200

    # Access revoked after removal.
    access_after = client.get(
        f"/api/meetings/{meeting_id}", headers=auth_headers(employee_token)
    )
    assert access_after.status_code == 403


def test_cannot_assign_admin_as_participant(client, test_engine):
    admin_token = signup_and_login(
        client, "Admin4", "admin4@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin4@example.com")

    other_admin_token = signup_and_login(
        client, "Admin5", "admin5@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin5@example.com")

    admin5_id = client.get(
        "/users/me", headers=auth_headers(other_admin_token)
    ).json()["id"]

    meeting_id = client.post(
        "/api/meetings/",
        json={"title": "Leads sync", "meeting_date": "2026-09-01T10:00:00", "transcript":"The release is Friday."},
        headers=auth_headers(admin_token),
    ).json()["id"]

    response = client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"user_id": admin5_id},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 400


# ============================================================
# TRANSCRIPT PROCESSING + STRUCTURED SUMMARY + NOTIFICATIONS
# (Phases 5 / 8 / 9 / 14 â€” with the LLM calls monkeypatched)
# ============================================================

def test_transcript_processing_generates_summary_and_notifies(
    client, test_engine
):
    admin_token = signup_and_login(
        client, "Admin6", "admin6@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin6@example.com")

    employee_token = signup_and_login(
        client, "Employee6", "emp6@example.com", "password123"
    )
    employee_id = client.get(
        "/users/me", headers=auth_headers(employee_token)
    ).json()["id"]

    meeting_id = client.post(
        "/api/meetings/",
        json={"title": "Launch review", "meeting_date": "2026-09-01T10:00:00", "transcript":"The release is Friday."},
        headers=auth_headers(admin_token),
    ).json()["id"]

    client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"user_id": employee_id},
        headers=auth_headers(admin_token),
    )

    # Upload transcript -> triggers process_meeting_automatically
    # synchronously in tests (TestClient runs BackgroundTasks inline
    # on request completion).
    response = client.put(
        f"/api/meetings/{meeting_id}/transcript",
        json={"transcript": "Kal frontend ka kaam complete karna hai."},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200

    meeting = client.get(
        f"/api/meetings/{meeting_id}", headers=auth_headers(admin_token)
    ).json()

    assert meeting["status"] == "ready"
    assert "Test overview" in meeting["summary"]
    assert meeting["action_items"][0]["task"] == "Fix login bug"
    assert meeting["action_items"][0]["assigned_to"] == "Ahmed"

    # Notification created for the assigned employee.
    notifications = client.get(
        "/api/notifications/", headers=auth_headers(employee_token)
    )
    assert notifications.status_code == 200
    assert len(notifications.json()) >= 1
    assert "Launch review" in notifications.json()[0]["message"]

    unread = client.get(
        "/api/notifications/unread-count", headers=auth_headers(employee_token)
    )
    assert unread.json()["unread_count"] >= 1


def test_empty_transcript_rejected(client, test_engine):
    admin_token = signup_and_login(
        client, "Admin7", "admin7@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin7@example.com")

    meeting_id = client.post(
        "/api/meetings/",
        json={"title": "Empty test", "meeting_date": "2026-09-01T10:00:00", "transcript":"The release is Friday."},
        headers=auth_headers(admin_token),
    ).json()["id"]

    response = client.put(
        f"/api/meetings/{meeting_id}/transcript",
        json={"transcript": "   "},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 400


# ============================================================
# EMPLOYEE MANAGEMENT (Phase 12)
# ============================================================

def test_admin_can_deactivate_and_reactivate_employee(client, test_engine):
    admin_token = signup_and_login(
        client, "Admin8", "admin8@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin8@example.com")

    signup_and_login(client, "Employee8", "emp8@example.com", "password123")
    employee_id = client.get(
        "/users/",
        params={"role": "employee"},
        headers=auth_headers(admin_token),
    ).json()
    employee_id = [u for u in employee_id if u["email"] == "emp8@example.com"][0]["id"]

    deactivate = client.patch(
        f"/users/{employee_id}/deactivate", headers=auth_headers(admin_token)
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    login_attempt = client.post(
        "/users/login",
        json={"email": "emp8@example.com", "password": "password123"},
    )
    assert login_attempt.status_code == 401

    reactivate = client.patch(
        f"/users/{employee_id}/activate", headers=auth_headers(admin_token)
    )
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_employee_cannot_list_users(client):
    token = signup_and_login(
        client, "Employee9", "emp9@example.com", "password123"
    )
    response = client.get("/users/", headers=auth_headers(token))
    assert response.status_code == 403


# ============================================================
# WEBHOOK (Phase 13)
# ============================================================

def test_webhook_disabled_without_secret_configured(client):
    response = client.post(
        "/api/webhooks/n8n/meetings",
        json={
            "title": "Auto meeting",
            "meeting_date": "2026-09-01T10:00:00",
            "transcript": "The release is Friday.",
            "transcript": "Some transcript text.",
        },
        headers={"X-Webhook-Secret": "anything"},
    )
    # N8N_WEBHOOK_SECRET is not set in the test environment, so the
    # endpoint must refuse rather than silently accept unauthenticated
    # requests.
    assert response.status_code == 503


# ============================================================
# ZOOM WEBHOOK
# ============================================================

def test_zoom_url_validation_handshake(client, monkeypatch):
    monkeypatch.setenv("ZOOM_WEBHOOK_SECRET_TOKEN", "test-zoom-secret")

    from app.config import settings
    monkeypatch.setattr(settings, "zoom_webhook_secret_token", "test-zoom-secret")

    response = client.post(
        "/api/webhooks/zoom",
        json={
            "event": "endpoint.url_validation",
            "payload": {"plainToken": "abc123"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["plainToken"] == "abc123"

    import hashlib
    import hmac
    expected = hmac.new(
        b"test-zoom-secret", b"abc123", hashlib.sha256
    ).hexdigest()
    assert body["encryptedToken"] == expected


def test_zoom_webhook_rejects_bad_signature(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "zoom_webhook_secret_token", "test-zoom-secret")

    response = client.post(
        "/api/webhooks/zoom",
        json={"event": "recording.completed", "payload": {"object": {}}},
        headers={
            "x-zm-request-timestamp": "12345",
            "x-zm-signature": "v0=wrong",
        },
    )
    assert response.status_code == 401


# ============================================================
# REPROCESS (stuck / failed meetings)
# ============================================================

def test_reprocess_stuck_meeting(client, test_engine):
    admin_token = signup_and_login(
        client, "Admin9", "admin9@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin9@example.com")

    meeting_id = client.post(
        "/api/meetings/",
        json={"title": "Stuck meeting", "meeting_date": "2026-09-01T10:00:00", "transcript":"The release is Friday."},
        headers=auth_headers(admin_token),
    ).json()["id"]

    client.put(
        f"/api/meetings/{meeting_id}/transcript",
        json={"transcript": "Some transcript."},
        headers=auth_headers(admin_token),
    )

    # The immediate response reflects the state at return time (before
    # the background task runs) â€” must be "processing".
    response = client.post(
        f"/api/meetings/{meeting_id}/reprocess",
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "processing"

    # TestClient runs BackgroundTasks synchronously before this call
    # returns, so a follow-up GET reflects the final state.
    final = client.get(
        f"/api/meetings/{meeting_id}", headers=auth_headers(admin_token)
    )
    assert final.json()["status"] == "ready"


def test_reprocess_requires_admin(client, test_engine):
    admin_token = signup_and_login(
        client, "Admin10", "admin10@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin10@example.com")

    meeting_id = client.post(
        "/api/meetings/",
        json={"title": "Meeting", "meeting_date": "2026-09-01T10:00:00", "transcript":"The release is Friday."},
        headers=auth_headers(admin_token),
    ).json()["id"]

    employee_token = signup_and_login(
        client, "Employee10", "emp10@example.com", "password123"
    )

    response = client.post(
        f"/api/meetings/{meeting_id}/reprocess",
        headers=auth_headers(employee_token),
    )
    assert response.status_code == 403


# ============================================================
# RAG relevance threshold (cosine distance regression guard)
# ============================================================

def test_relevance_threshold_is_cosine_scale():
    """
    Regression guard for the bug where the Chroma collection defaulted
    to raw L2 distance while the relevance gate assumed cosine
    distance (0-2 range) â€” causing every chat answer to be rejected as
    'not found'. Cosine distance can never exceed 2, so the threshold
    must stay within that range or the same class of bug reappears.
    """
    from app.routes.meetings import MAX_RELEVANCE_DISTANCE
    assert 0 < MAX_RELEVANCE_DISTANCE <= 2

    from app.services.vector_store import collection
    # Chroma's collection metadata should explicitly request cosine
    # distance rather than relying on the (mismatched) L2 default.
    assert collection.metadata.get("hnsw:space") == "cosine"


def test_chat_falls_back_to_legacy_collection_for_old_meetings(
    client, test_engine, monkeypatch
):
    """
    Meetings embedded BEFORE the collection-rename fix have their
    chunks sitting only in the old ("meeting_transcripts") collection.
    The chatbot must still be able to answer for them without
    requiring every existing meeting to be manually reprocessed.
    """
    admin_token = signup_and_login(
        client, "Admin11", "admin11@example.com", "adminpass123"
    )
    make_admin(test_engine, "admin11@example.com")

    meeting_id = client.post(
        "/api/meetings/",
        json={"title": "Old meeting", "meeting_date": "2026-09-01T10:00:00", "transcript":"The release is Friday."},
        headers=auth_headers(admin_token),
    ).json()["id"]

    # Legacy storage had no SQL transcript/chunks; create that historical state explicitly.
    from app.database import SessionLocal
    from app.models import Meeting, TranscriptChunk
    with SessionLocal() as db:
        db.get(Meeting, meeting_id).transcript = None
        db.query(TranscriptChunk).filter_by(meeting_id=meeting_id).delete()
        db.commit()

    # Simulate: this meeting was embedded before the fix, so its
    # chunks exist ONLY in the legacy collection, not the new one.
    from app.services.vector_store import _legacy_collection

    _legacy_collection.upsert(
        ids=[f"meeting_{meeting_id}_chunk_0"],
        documents=["The team decided to launch the new website on Friday."],
        embeddings=[[0.1] * 8],
        metadatas=[{"meeting_id": meeting_id}],
    )

    from app.routes import meetings as meetings_module

    monkeypatch.setattr(
        meetings_module, "create_embedding", lambda text: [0.1] * 8
    )
    monkeypatch.setattr(
        meetings_module,
        "generate_answer",
        lambda question, context, chat_history=None: (
            "The website launches Friday, per the transcript."
        ),
    )
    monkeypatch.setattr(
        meetings_module,
        "resolve_followup_question",
        lambda question, chat_history=None: question,
    )

    response = client.post(
        f"/api/meetings/{meeting_id}/ask",
        json={"question": "When does the website launch?"},
        headers=auth_headers(admin_token),
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "couldn't find enough information" not in answer.lower()
    assert "Friday" in answer

