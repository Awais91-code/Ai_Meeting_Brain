from datetime import datetime

from pydantic import BaseModel, Field, field_validator
import json


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    meeting_date: datetime
    duration_minutes: int | None = None
    transcript: str | None = None
    participant_ids: list[int] = Field(default_factory=list)
    team_ids: list[int] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value):
        if not value.strip():
            raise ValueError("Meeting title cannot be empty")
        return value.strip()


class ActionItem(BaseModel):
    task: str
    assigned_to: str = "Unassigned"
    deadline: str = "Not specified"
    status: str = "Pending"


class MeetingResponse(BaseModel):
    meeting_url: str | None = None
    id: int
    title: str
    meeting_date: datetime
    duration_minutes: int | None
    organizer_id: int
    transcript: str | None
    summary: str | None
    action_items: list[ActionItem] = []
    processing_error: str | None = None
    status: str
    created_at: datetime

    model_config = {
        "from_attributes": True,
    }

    @field_validator("action_items", mode="before")
    @classmethod
    def parse_action_items(cls, value):
        # The DB stores action_items as a JSON-encoded string (Text
        # column, for SQLite/PostgreSQL portability). Decode it here so
        # API responses always return a real JSON array.
        if value is None or value == "":
            return []

        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return []

        return value


class MeetingStats(BaseModel):
    total: int
    uploaded: int
    processing: int
    ready: int
    processing_failed: int
