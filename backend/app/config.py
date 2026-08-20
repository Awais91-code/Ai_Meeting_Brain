# app/config.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
ENV_FILE = ROOT_DIR / ".env"

class Settings(BaseSettings):
    app_name: str = Field(default="AI Meeting Brain", validation_alias="APP_NAME")
    app_version: str = Field(default="1.0.0", validation_alias="APP_VERSION")
    debug: bool = Field(default=False, validation_alias="DEBUG")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    bytez_api_key: str = Field(default="", validation_alias="BYTEZ_API_KEY")
    openrouter_api_key: str = Field(default="",validation_alias="OPENROUTER_API_KEY")
    secret_key: str = Field(default="", validation_alias="SECRET_KEY")

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

settings = Settings()

# Debug
if settings.database_url:
    print(f"✅ DATABASE_URL loaded successfully!")
else:
    print(f"❌ DATABASE_URL NOT FOUND in {ENV_FILE}")
    print(f"   File exists: {ENV_FILE.exists()}")