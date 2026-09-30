from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Team, TeamMember, User
from app.schemas.team import TeamCreate, TeamMembersUpdate, TeamResponse, TeamUpdate
from app.security.auth import get_current_user, require_role

router = APIRouter(prefix="/api/teams", tags=["Teams"])


def _serialize(team: Team, db: Session) -> TeamResponse:
    rows = (
        db.query(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .filter(TeamMember.team_id == team.id)
        .order_by(User.name)
        .all()
    )
    active = [(membership, user) for membership, user in rows if user.is_active]
    return TeamResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        created_at=team.created_at,
        member_ids=[user.id for _, user in rows],
        member_names=[user.name for _, user in rows],
        active_member_count=len(active),
    )


@router.get("/", response_model=list[TeamResponse])
def list_teams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Team)
    if current_user.role != "admin":
        query = (
            query.join(TeamMember, TeamMember.team_id == Team.id)
            .filter(TeamMember.user_id == current_user.id)
        )
    teams = query.order_by(Team.name).all()
    return [_serialize(team, db) for team in teams]


@router.post("/", response_model=TeamResponse)
def create_team(
    payload: TeamCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    team = Team(name=payload.name, description=(payload.description or "").strip() or None)
    db.add(team)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "A team with this name already exists.")
    db.refresh(team)
    return _serialize(team, db)


@router.put("/{team_id}", response_model=TeamResponse)
def update_team(
    team_id: int,
    payload: TeamUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    if payload.name is not None:
        team.name = payload.name
    if payload.description is not None:
        team.description = payload.description.strip() or None

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "A team with this name already exists.")
    db.refresh(team)
    return _serialize(team, db)


@router.put("/{team_id}/members", response_model=TeamResponse)
def replace_team_members(
    team_id: int,
    payload: TeamMembersUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    requested = set(payload.user_ids)
    if requested:
        users = db.query(User).filter(User.id.in_(requested)).all()
        valid = {
            user.id
            for user in users
            if user.role == "employee" and user.is_active
        }
        if valid != requested:
            raise HTTPException(
                400,
                "Teams can contain only active employee accounts.",
            )

    db.query(TeamMember).filter(TeamMember.team_id == team_id).delete(
        synchronize_session=False
    )
    for user_id in sorted(requested):
        db.add(TeamMember(team_id=team_id, user_id=user_id))
    db.commit()
    db.refresh(team)
    return _serialize(team, db)


@router.delete("/{team_id}")
def delete_team(
    team_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")
    db.delete(team)
    db.commit()
    return {"message": "Team deleted successfully.", "team_id": team_id}
