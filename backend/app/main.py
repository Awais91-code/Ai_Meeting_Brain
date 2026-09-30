from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.models import User
from app.routes.users import router as users_router
from app.routes.meetings import router as meetings_router
from app.routes.notifications import router as notifications_router
from app.routes.webhooks import router as webhooks_router
from app.routes.capture import router as capture_router
from app.routes.live import router as live_router
from app.routes.conference import router as conference_router
from app.routes.teams import router as teams_router

# Resolve static/template directories relative to this file, not the
# process's current working directory — otherwise "uvicorn app.main:app"
# only works if launched from exactly one specific folder.
BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app):
    worker = None
    if settings.worker_enabled:
        from app.services.worker import start_worker
        worker = start_worker()
    yield
    if worker:
        worker[0].set()
        worker[1].join(timeout=2)


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version=settings.app_version,
)

# --------------------------------------------------------------------
# SECURITY: startup checks (Phase 17)
# --------------------------------------------------------------------
if not settings.secret_key:
    raise RuntimeError(
        "SECRET_KEY is not set. Refusing to start with an empty JWT "
        "signing secret — set SECRET_KEY in your .env file."
    )

if len(settings.secret_key) < 32 or settings.secret_key.startswith(("ai-meeting-brain-development", "CHANGE_ME")):
    raise RuntimeError("SECRET_KEY must be a unique random secret of at least 32 characters, not the development default.")

# --------------------------------------------------------------------
# CORS: only enabled if explicit origins are configured. This app is
# served same-origin (Jinja2 templates + same-origin fetch calls), so
# by default no cross-origin browser access is allowed at all.
# --------------------------------------------------------------------
if settings.cors_allowed_origins:
    origins = [
        origin.strip()
        for origin in settings.cors_allowed_origins.split(",")
        if origin.strip()
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(users_router)
app.include_router(meetings_router)
app.include_router(notifications_router)
app.include_router(webhooks_router)
app.include_router(capture_router)
app.include_router(live_router)
app.include_router(conference_router)
app.include_router(teams_router)


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/live", include_in_schema=False)
@app.get("/live/{session_id}", include_in_schema=False)
@app.get("/meetings/{meeting_id}/live", include_in_schema=False)
def capture_page(request: Request, meeting_id: int | None = None, session_id: str | None = None):
    return templates.TemplateResponse(request=request, name="capture.html",
                                      context={"meeting_id": meeting_id, "session_id": session_id})


@app.get("/")
def root():
    return {
        "message": "AI Meeting Brain API is running",
        "version": settings.app_version,
    }


@app.get("/db-test")
def database_test():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))

    return {
        "database": "connected",
        "result": result.scalar(),
    }


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request},
    )


@app.get("/forgot-password", include_in_schema=False)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={"request": request},
    )


@app.get("/reset-password", include_in_schema=False)
def reset_password_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        context={"request": request},
    )


@app.get("/dashboard", include_in_schema=False)
def dashboard_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"request": request},
    )


@app.get("/devices", include_in_schema=False)
def devices_page(request: Request):
    return templates.TemplateResponse(request=request, name="devices.html", context={})


@app.get("/meetings/{meeting_id}", include_in_schema=False)
def meeting_page(request: Request, meeting_id: int):
    return templates.TemplateResponse(
        request=request,
        name="meeting.html",
        context={
            "request": request,
            "meeting_id": meeting_id,
        },
    )


@app.get(
    "/admin/meetings/{meeting_id}/edit",
    include_in_schema=False,
)
def edit_meeting_page(
    request: Request,
    meeting_id: int,
):
    return templates.TemplateResponse(
        request=request,
        name="edit_meeting.html",
        context={
            "request": request,
            "meeting_id": meeting_id,
        },
    )


@app.get(
    "/admin",
    include_in_schema=False,
)
def admin_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "request": request,
        },
    )


@app.get(
    "/admin/employees",
    include_in_schema=False,
)
def employees_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="employees.html",
        context={
            "request": request,
        },
    )
