import os
import sys
import tempfile
from pathlib import Path

# Make sure tests never touch the developer's real Postgres DB, real
# .env secrets, or real Chroma data, regardless of what's on disk.
# A real temp FILE (not ":memory:") is used so that the background
# task's own SessionLocal() connection (opened fresh, independent of
# the request's session) sees the exact same schema and data as the
# test's HTTP requests â€” a ":memory:" SQLite DB is private per
# connection and would silently diverge between the two.
_TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_TEST_DB_FD)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-32ch")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-used")
os.environ.setdefault("BYTEZ_API_KEY", "test-key-not-used")
os.environ.setdefault("APP_NAME", "AI Meeting Brain (test)")
os.environ["CHROMA_DB_PATH"] = tempfile.mkdtemp(suffix="_chroma")
os.environ["DATA_DIR"] = tempfile.mkdtemp(suffix="_meeting_data")
os.environ["WORKER_ENABLED"] = "false"
os.environ["MANAGED_JITSI"] = "false"
os.environ["LLM_PROVIDER"] = "extractive"
os.environ["EMBEDDING_PROVIDER"] = "local"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal, get_db
from app import models  # noqa: F401  (register all models on Base.metadata)


@pytest.fixture()
def test_engine():
    """The single, shared SQLite file engine used by both the test's
    HTTP requests AND any background task the request kicks off."""
    Base.metadata.create_all(bind=engine)
    yield engine
    # Clear all tables between tests (cheaper & simpler than recreating
    # the schema, and keeps the same shared file/engine for the whole
    # test session).
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture()
def client(test_engine, monkeypatch):
    from app.main import app

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Never call the real OpenRouter API in tests â€” there is no
    # network path to it in this environment anyway, and tests should
    # be deterministic and fast regardless.
    from app.services import meeting_processor

    monkeypatch.setattr(
        meeting_processor,
        "create_embedding",
        lambda text: [0.0] * 8,
    )
    monkeypatch.setattr(
        meeting_processor, "add_chunks", lambda **kwargs: None
    )
    monkeypatch.setattr(
        meeting_processor, "delete_chunks", lambda meeting_id: None
    )
    monkeypatch.setattr(
        meeting_processor,
        "generate_structured_summary",
        lambda transcript: {
            "overview": "Test overview of the meeting.",
            "key_points": ["Point one"],
            "decisions": ["Decision one"],
            "action_items": [
                {
                    "task": "Fix login bug",
                    "assigned_to": "Ahmed",
                    "deadline": "Friday",
                    "status": "Pending",
                }
            ],
            "deadlines": ["Friday"],
        },
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def signup_and_login(client, name, email, password, role="employee"):
    # Employee accounts are provisioned by admins, never by public signup.
    from app.models import User
    from app.security.auth import hash_password
    with SessionLocal() as db:
        db.add(User(name=name, email=email, password_hash=hash_password(password), role=role))
        db.commit()

    login_response = client.post(
        "/users/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200, login_response.text
    token = login_response.json()["access_token"]

    return token


def make_admin(test_engine, email):
    """Self-registration always creates 'employee' accounts by design
    (see users.py) â€” promote the account to admin directly in the test
    DB, the way a real deployment would via its first-admin seed
    script."""
    from sqlalchemy.orm import Session
    from app.models import User

    with Session(test_engine) as session:
        user = session.query(User).filter(User.email == email).first()
        user.role = "admin"
        session.commit()
