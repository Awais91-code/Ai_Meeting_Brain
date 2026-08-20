from pydantic import BaseModel


class TranscriptUpdate(BaseModel):
    transcript: str