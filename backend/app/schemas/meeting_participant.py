from pydantic import BaseModel


class MeetingParticipantCreate(BaseModel):
    user_id: int


class ParticipantUser(BaseModel):
    id: int
    name: str
    email: str

    model_config = {
        "from_attributes": True,
    }


class MeetingParticipantResponse(BaseModel):
    id: int
    meeting_id: int
    user_id: int
    user: ParticipantUser | None = None

    model_config = {
        "from_attributes": True,
    }
