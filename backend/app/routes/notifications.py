from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Notification, User
from app.schemas.notification import NotificationResponse
from app.security.auth import get_current_user

router = APIRouter(
    prefix="/api/notifications",
    tags=["Notifications"],
)


@router.get("/", response_model=list[NotificationResponse])
def list_my_notifications(
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(Notification).where(
        Notification.user_id == current_user.id
    )

    if unread_only:
        query = query.where(Notification.is_read.is_(False))

    query = query.order_by(Notification.created_at.desc()).limit(50)

    from app.services.live_sessions import read_session, admission_open, user_has_session_access
    results = []
    for notification in db.scalars(query).all():
        item = NotificationResponse.model_validate(notification)
        if item.live_session_id:
            try:
                data = read_session(item.live_session_id)
                item.join_available = admission_open(data) and user_has_session_access(data, current_user, db)
            except HTTPException:
                pass
        results.append(item)
    return results


@router.get("/unread-count")
def unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .count()
    )

    return {"unread_count": count}


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = db.get(Notification, notification_id)

    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    db.commit()
    db.refresh(notification)

    return notification


@router.patch("/mark-all-read")
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read.is_(False),
    ).update({"is_read": True}, synchronize_session=False)

    db.commit()

    return {"message": "All notifications marked as read."}
