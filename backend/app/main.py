from fastapi import FastAPI
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.models import User
from app.routes.users import router as users_router
from app.routes.meetings import router as meetings_router



app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

app.include_router(users_router)
app.include_router(meetings_router)

print("DATABASE URL:", settings.database_url)

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