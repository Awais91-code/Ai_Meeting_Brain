from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "employee"


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    is_active: bool = True

    model_config = {
        "from_attributes": True
    }


class UserWithMeetingCount(UserResponse):
    assigned_meeting_count: int = 0


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class AdminCreateUser(BaseModel):
    """Used by an admin to create either an employee or another admin."""
    name: str
    email: EmailStr
    password: str
    role: str = "employee"


class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    role: str | None = None


class PasswordResetRequest(BaseModel):
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str
