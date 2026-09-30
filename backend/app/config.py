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
    llm_provider: str = Field(default="auto", validation_alias="LLM_PROVIDER")
    chat_model: str = Field(default="openrouter/free", validation_alias="CHAT_MODEL")
    ollama_model: str = Field(default="qwen2.5:3b", validation_alias="OLLAMA_MODEL")
    ollama_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_URL")
    embedding_provider: str = Field(default="local", validation_alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="", validation_alias="EMBEDDING_MODEL")
    worker_enabled: bool = Field(default=True, validation_alias="WORKER_ENABLED")
    # large-v3 materially improves multilingual/Urdu accuracy over small.
    # It is larger/slower on CPU, so device/compute type remain configurable.
    whisper_model: str = Field(default="large-v3", validation_alias="WHISPER_MODEL")
    whisper_prefer_large_v3: bool = Field(default=True, validation_alias="WHISPER_PREFER_LARGE_V3")
    whisper_device: str = Field(default="cpu", validation_alias="WHISPER_DEVICE")
    whisper_compute_type: str = Field(default="int8", validation_alias="WHISPER_COMPUTE_TYPE")
    whisper_beam_size: int = Field(default=8, ge=1, le=20, validation_alias="WHISPER_BEAM_SIZE")
    whisper_cpu_threads: int = Field(default=0, ge=0, le=64, validation_alias="WHISPER_CPU_THREADS")
    whisper_language: str = Field(default="", validation_alias="WHISPER_LANGUAGE")
    data_dir: str = Field(default=str(ROOT_DIR / "backend" / "data"), validation_alias="DATA_DIR")
    max_audio_mb: int = Field(default=250, ge=1, validation_alias="MAX_AUDIO_MB")
    jitsi_domain: str = Field(default="meet.jit.si", pattern=r"^[a-zA-Z0-9.-]+(?::[0-9]+)?$", validation_alias="JITSI_DOMAIN")
    jitsi_app_id: str = Field(default="meeting-brain", validation_alias="JITSI_APP_ID")
    jitsi_app_secret: str = Field(default="", validation_alias="JITSI_APP_SECRET")
    jitsi_jwt_subject: str = Field(default="meet.jitsi", validation_alias="JITSI_JWT_SUBJECT")
    jitsi_require_auth: bool = Field(default=False, validation_alias="JITSI_REQUIRE_AUTH")
    managed_jitsi: bool = Field(default=False, validation_alias="MANAGED_JITSI")
    jitsi_ca_bundle: str = Field(default="", validation_alias="JITSI_CA_BUNDLE")

    # Password recovery. Configure SMTP for real delivery. Development mode
    # may expose the one-time reset URL only for local/private-network demos.
    smtp_host: str = Field(default="", validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=587, ge=1, le=65535, validation_alias="SMTP_PORT")
    smtp_username: str = Field(default="", validation_alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", validation_alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", validation_alias="SMTP_FROM")
    smtp_starttls: bool = Field(default=True, validation_alias="SMTP_STARTTLS")
    smtp_use_ssl: bool = Field(default=False, validation_alias="SMTP_USE_SSL")
    password_reset_expire_minutes: int = Field(
        default=30, ge=5, le=1440, validation_alias="PASSWORD_RESET_EXPIRE_MINUTES"
    )
    password_reset_dev_mode: bool = Field(
        default=False, validation_alias="PASSWORD_RESET_DEV_MODE"
    )

    # Shared secret n8n (or any external caller) must send in the
    # X-Webhook-Secret header to create meetings via the automation
    # webhook (Phase 13). Leave unset to disable the webhook entirely.
    n8n_webhook_secret: str = Field(
        default="", validation_alias="N8N_WEBHOOK_SECRET"
    )

    # Comma-separated list of allowed browser origins for CORS.
    # Defaults to "" (no cross-origin JS access) since this app is
    # served and consumed from the same origin (Jinja2 + same-origin
    # fetch calls) — only set this if you split frontend/backend hosts.
    cors_allowed_origins: str = Field(
        default="", validation_alias="CORS_ALLOWED_ORIGINS"
    )

    # Optional override for where Chroma stores its on-disk index.
    # Defaults to backend/chroma_db when unset (see vector_store.py).
    chroma_db_path: str = Field(
        default="", validation_alias="CHROMA_DB_PATH"
    )

    # ---- Zoom integration (Phase 13 extension) ----
    # Create a "Server-to-Server OAuth" app in the Zoom App Marketplace
    # to get these three values. Used to fetch an access token for
    # downloading cloud recording transcripts.
    zoom_account_id: str = Field(default="", validation_alias="ZOOM_ACCOUNT_ID")
    zoom_client_id: str = Field(default="", validation_alias="ZOOM_CLIENT_ID")
    zoom_client_secret: str = Field(
        default="", validation_alias="ZOOM_CLIENT_SECRET"
    )
    # The "Secret Token" shown on the app's Webhook/Feature page in the
    # Zoom Marketplace — used to verify webhook authenticity and to
    # answer Zoom's URL-validation handshake.
    zoom_webhook_secret_token: str = Field(
        default="", validation_alias="ZOOM_WEBHOOK_SECRET_TOKEN"
    )

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

settings = Settings()

# # Debug
# if settings.database_url:
#     print("DATABASE_URL loaded successfully!")
# else:
#     print("DATABASE_URL NOT FOUND in {}".format(ENV_FILE))
#     print("File exists: {}".format(ENV_FILE.exists()))
