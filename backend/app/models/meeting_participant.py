from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"

    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "user_id",
            name="uq_meeting_participant",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    meeting = relationship(
        "Meeting",
        back_populates="participants",
    )

    user = relationship(
        "User",
        back_populates="meeting_participations",
    )