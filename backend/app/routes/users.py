from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    Meeting,
    MeetingParticipant,
    MeetingTeam,
    PasswordResetToken,
    TeamMember,
    User,
)

from app.schemas.user import (
    UserCreate,
    UserResponse,
    UserWithMeetingCount,
    UserLogin,
    TokenResponse,
    AdminCreateUser,
    UserUpdate,
    PasswordResetRequest,
    ForgotPasswordRequest,
    PasswordResetConfirm,
)
from app.services.password_reset import hash_reset_token, new_reset_token, send_reset_email

from app.security.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_role,
)

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


@router.post("/refresh", response_model=TokenResponse)
def refresh_session(current_user: User = Depends(get_current_user)):
    """Renew an active, validated session while a long recording is open."""
    return {"access_token": create_access_token(current_user.id, current_user.role), "token_type": "bearer"}


@router.post("/", response_model=UserResponse)
def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Provision an employee. Public self-registration is deliberately disabled."""

    existing = (
        db.query(User)
        .filter(User.email == user_data.email)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists.",
        )

    user = User(
        name=user_data.name,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        role="employee",
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@router.get("/me", response_model=UserResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return current_user


@router.get("/admin-test")
def admin_test(
    current_user: User = Depends(require_role("admin")),
):
    return {
        "message": "You are an admin",
        "user_id": current_user.id,
    }


# ============================================================
# ADMIN: EMPLOYEE / USER MANAGEMENT  (Phase 12)
# ============================================================

@router.get("/", response_model=list[UserWithMeetingCount])
def list_users(
    role: str | None = None,
    q: str | None = None,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """List users for the admin panel (e.g. the employee picker in the
    participant-management modal, and the Employee Management page)."""

    query = db.query(User)

    if role:
        query = query.filter(User.role == role)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(User.name.ilike(like), User.email.ilike(like))
        )

    users = query.order_by(User.name).all()

    # Count unique meetings reachable either directly or through a team.
    access_map: dict[int, set[int]] = {}
    for user_id, meeting_id in db.query(
        MeetingParticipant.user_id,
        MeetingParticipant.meeting_id,
    ).all():
        access_map.setdefault(user_id, set()).add(meeting_id)

    for user_id, meeting_id in (
        db.query(TeamMember.user_id, MeetingTeam.meeting_id)
        .join(MeetingTeam, MeetingTeam.team_id == TeamMember.team_id)
        .all()
    ):
        access_map.setdefault(user_id, set()).add(meeting_id)

    results = []
    for user in users:
        data = UserWithMeetingCount.model_validate(user)
        data.assigned_meeting_count = len(access_map.get(user.id, set()))
        results.append(data)

    return results


@router.post("/admin-create", response_model=UserResponse)
def admin_create_user(
    user_data: AdminCreateUser,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Admin-only endpoint to create employees (or additional admins)."""

    if user_data.role not in ("employee", "admin"):
        raise HTTPException(
            status_code=400,
            detail="Role must be 'employee' or 'admin'.",
        )

    existing = (
        db.query(User)
        .filter(User.email == user_data.email)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists.",
        )

    user = User(
        name=user_data.name,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        role=user_data.role,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user_data.name is not None:
        user.name = user_data.name

    if user_data.email is not None:
        duplicate = (
            db.query(User)
            .filter(User.email == user_data.email, User.id != user_id)
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=400,
                detail="Another account already uses this email.",
            )
        user.email = user_data.email

    if user_data.role is not None:
        if user_data.role not in ("employee", "admin"):
            raise HTTPException(
                status_code=400,
                detail="Role must be 'employee' or 'admin'.",
            )
        if user.id == current_user.id and user_data.role != "admin":
            raise HTTPException(
                status_code=400,
                detail="You cannot remove your own admin role.",
            )
        user.role = user_data.role

    db.commit()
    db.refresh(user)

    return user


@router.patch("/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot disable your own account.",
        )

    user.is_active = False
    db.commit()
    db.refresh(user)

    return user


@router.patch("/{user_id}/activate", response_model=UserResponse)
def activate_user(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    db.commit()
    db.refresh(user)

    return user


@router.put("/{user_id}/password")
def reset_password(
    user_id: int,
    data: PasswordResetRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if len(data.new_password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters.",
        )

    user.password_hash = hash_password(data.new_password)
    db.commit()

    return {"message": "Password updated successfully."}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """
    Safe delete: an employee with no meeting history can be removed
    outright. A user who organized meetings (or has any history worth
    keeping) is deactivated instead of deleted, so historical meeting
    data is never silently lost because of a user deletion.
    """

    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your own account.",
        )

    organizes_meetings = (
        db.query(Meeting)
        .filter(Meeting.organizer_id == user_id)
        .first()
    )

    from app.services.live_sessions import has_user_history
    if organizes_meetings or has_user_history(user_id):
        # Preserve meeting history: disable instead of deleting.
        user.is_active = False
        db.commit()

        return {
            "message": (
                "This user has meeting or live-session history, so the "
                "account was disabled instead of deleted to preserve "
                "meeting history."
            ),
            "deleted": False,
            "deactivated": True,
        }

    try:
        db.delete(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        user.is_active = False
        db.commit()
        return {
            "message": (
                "This user has related records, so the account was "
                "disabled instead of deleted."
            ),
            "deleted": False,
            "deactivated": True,
        }

    return {
        "message": "User deleted successfully.",
        "deleted": True,
        "deactivated": False,
    }


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this user.",
        )

    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return user


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a short-lived, one-time reset link without revealing account existence."""
    generic = {
        "message": (
            "If an active account exists for that email, password reset "
            "instructions have been created."
        )
    }

    user = (
        db.query(User)
        .filter(User.email == payload.email, User.is_active.is_(True))
        .first()
    )
    if not user:
        return generic

    raw_token, token_hash, expires_at = new_reset_token()

    # Invalidate older outstanding links for this account.
    now = datetime.now(timezone.utc)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    record = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()

    reset_url = str(request.base_url).rstrip("/") + "/reset-password?token=" + raw_token

    delivered = False
    try:
        delivered = send_reset_email(user.email, reset_url)
    except Exception:
        # Do not disclose SMTP details or account existence to the caller.
        delivered = False

    # Private demo mode makes local recovery usable without an SMTP account.
    # It is intentionally opt-in because anyone knowing an employee email
    # could otherwise request and receive the reset URL.
    development_delivery = settings.password_reset_dev_mode
    if development_delivery:
        return {
            **generic,
            "delivery": "development",
            "reset_url": reset_url,
            "expires_in_minutes": settings.password_reset_expire_minutes,
        }

    if delivered:
        return {**generic, "delivery": "email"}

    return {
        **generic,
        "delivery": "unavailable",
        "help": "Ask your workspace administrator to reset the password.",
    }


@router.post("/reset-password")
def confirm_password_reset(
    payload: PasswordResetConfirm,
    db: Session = Depends(get_db),
):
    if len(payload.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    token_hash = hash_reset_token(payload.token)
    record = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
        .first()
    )

    if not record:
        raise HTTPException(400, "This password reset link is invalid or has already been used.")

    now = datetime.now(timezone.utc)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        record.used_at = now
        db.commit()
        raise HTTPException(400, "This password reset link has expired. Request a new one.")

    user = db.get(User, record.user_id)
    if not user or not user.is_active:
        record.used_at = now
        db.commit()
        raise HTTPException(400, "This password reset link is no longer valid.")

    user.password_hash = hash_password(payload.new_password)
    record.used_at = now

    # Invalidate any other outstanding links issued for the account.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.id != record.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    db.commit()
    return {"message": "Password updated. You can now sign in with your new password."}


@router.post("/login", response_model=TokenResponse)
def login(
    user_data: UserLogin,
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.email == user_data.email)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not verify_password(
        user_data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="This account has been disabled. Contact an administrator.",
        )

    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }
