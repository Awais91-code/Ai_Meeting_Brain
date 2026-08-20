from pydantic import BaseModel


class MeetingParticipantCreate(BaseModel):
    user_id: int


class MeetingParticipantResponse(BaseModel):
    id: int
    meeting_id: int
    user_id: int

    model_config = {
        "from_attributes": True,
    }
