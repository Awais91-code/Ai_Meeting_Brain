from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Team name cannot be empty")
        return value


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Team name cannot be empty")
        return value


class TeamMembersUpdate(BaseModel):
    user_ids: list[int] = Field(default_factory=list)


class TeamResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: datetime
    member_ids: list[int] = Field(default_factory=list)
    member_names: list[str] = Field(default_factory=list)
    active_member_count: int = 0

    model_config = {"from_attributes": True}
