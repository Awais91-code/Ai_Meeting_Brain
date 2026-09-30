from sqlalchemy.orm import Session

from app.models import Meeting, MeetingParticipant, MeetingTeam, Notification, TeamMember, User


def announce_live_session(data, db):
    """Called under the session lock; safe on join retries and worker recovery."""
    if not data.get("started_at"):
        return
    existing = {
        r[0]
        for r in db.query(Notification.user_id)
        .filter_by(live_session_id=data["session_id"])
        .all()
    }

    # New sessions notify only explicitly selected employees and members of
    # selected teams. Legacy sessions (without access fields) keep the old
    # "all employees" behavior so unfinished drafts remain recoverable.
    if "invited_user_ids" in data or "team_ids" in data:
        recipient_ids = set(data.get("invited_user_ids", []))
        team_ids = data.get("team_ids", [])
        if team_ids:
            recipient_ids.update(
                row[0]
                for row in db.query(TeamMember.user_id)
                .filter(TeamMember.team_id.in_(team_ids))
                .all()
            )
        recipients = (
            db.query(User)
            .filter(
                User.id.in_(recipient_ids or {-1}),
                User.is_active.is_(True),
                User.role == "employee",
            )
            .all()
        )
    else:
        recipients = (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                User.id != data["organizer_id"],
                User.role.in_(["admin", "employee"]),
            )
            .all()
        )

    host = db.get(User, data["organizer_id"])
    name = host.name if host else "Your administrator"
    for user in recipients:
        if user.id not in existing:
            db.add(Notification(user_id=user.id, live_session_id=data["session_id"],
                message=f'{name} started "{data["title"]}". Join the live meeting.'[:500]))
    db.commit()


def notify_meeting_ready(meeting: Meeting, db: Session) -> None:
    """
    Create an in-app notification for every employee assigned to a
    meeting once its summary/action items are ready, plus one for the
    organizer. Cheap, dependency-free (no paid email/SMS service),
    which fits a student FYP demo.
    """

    recipient_ids = set()

    participants = (
        db.query(MeetingParticipant)
        .filter(MeetingParticipant.meeting_id == meeting.id)
        .all()
    )

    for participant in participants:
        recipient_ids.add(participant.user_id)

    team_ids = [
        row[0]
        for row in db.query(MeetingTeam.team_id)
        .filter(MeetingTeam.meeting_id == meeting.id)
        .all()
    ]
    if team_ids:
        recipient_ids.update(
            row[0]
            for row in db.query(TeamMember.user_id)
            .join(User, User.id == TeamMember.user_id)
            .filter(
                TeamMember.team_id.in_(team_ids),
                User.is_active.is_(True),
                User.role == "employee",
            )
            .all()
        )

    recipient_ids.add(meeting.organizer_id)

    message = f'The summary for "{meeting.title}" is ready to view.'

    for user_id in recipient_ids:
        db.add(
            Notification(
                user_id=user_id,
                meeting_id=meeting.id,
                message=message,
            )
        )

    db.commit()
