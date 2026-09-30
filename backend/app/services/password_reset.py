"""Password-reset token creation and SMTP delivery.

Tokens are stored only as SHA-256 hashes. The raw token is sent to the user
once and is never persisted in the database.
"""
from __future__ import annotations

import hashlib
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app.config import settings


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_reset_token() -> tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(32)
    digest = hash_reset_token(raw)
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.password_reset_expire_minutes
    )
    return raw, digest, expires


def send_reset_email(recipient: str, reset_url: str) -> bool:
    """Return True when SMTP delivery succeeded, False when SMTP is not configured."""
    if not settings.smtp_host or not settings.smtp_from:
        return False

    message = EmailMessage()
    message["Subject"] = "Reset your AI Meeting Brain password"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        "A password reset was requested for your AI Meeting Brain account.\n\n"
        f"Open this link to choose a new password:\n{reset_url}\n\n"
        f"This link expires in {settings.password_reset_expire_minutes} minutes. "
        "If you did not request this, you can ignore this email."
    )

    if settings.smtp_use_ssl:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)

    try:
        if settings.smtp_starttls and not settings.smtp_use_ssl:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
        return True
    finally:
        try:
            server.quit()
        except Exception:
            pass
