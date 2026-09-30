from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Meeting(Base):
    __tablename__ = "meetings"

    source_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recording_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    meeting_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    duration_minutes: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    transcript: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # JSON-encoded list of structured action items:
    # [{"task": ..., "assigned_to": ..., "deadline": ..., "status": ...}]
    # Stored as Text (not a native JSON column) so this works identically
    # on SQLite and PostgreSQL without changing the existing DB engine.
    action_items: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Why automatic processing failed, shown to the admin so a stuck
    # "processing_failed" meeting is actionable instead of a dead end.
    processing_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="uploaded",
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    organizer = relationship(
        "User",
        backref="meetings",
    )

    participants = relationship(
        "MeetingParticipant",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )
