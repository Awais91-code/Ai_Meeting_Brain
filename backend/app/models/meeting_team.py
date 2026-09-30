from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MeetingTeam(Base):
    __tablename__ = "meeting_teams"
    __table_args__ = (
        UniqueConstraint("meeting_id", "team_id", name="uq_meeting_team"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )

    meeting = relationship("Meeting")
    team = relationship("Team", back_populates="meeting_links")
