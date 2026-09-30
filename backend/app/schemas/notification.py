from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: int
    meeting_id: int | None = None
    live_session_id: str | None = None
    join_available: bool = False
    message: str
    is_read: bool
    created_at: datetime

    model_config = {
        "from_attributes": True,
    }
