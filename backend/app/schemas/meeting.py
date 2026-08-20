from datetime import datetime

from pydantic import BaseModel


class MeetingCreate(BaseModel):
    title: str
    meeting_date: datetime
    duration_minutes: int | None = None
    transcript: str | None = None


class MeetingResponse(BaseModel):
    id: int
    title: str
    meeting_date: datetime
    duration_minutes: int | None
    organizer_id: int
    transcript: str | None
    summary: str | None
    status: str
    created_at: datetime

    model_config = {
        "from_attributes": True
    }