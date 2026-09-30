"""
Zoom integration service.

Flow (see routes/webhooks.py for the receiving end):

    Zoom meeting ends
        -> Zoom auto-generates a cloud recording + transcript (VTT)
        -> Zoom fires a "recording.completed" webhook to our endpoint
        -> we fetch a Server-to-Server OAuth token
        -> we download the TRANSCRIPT file using that token
        -> we convert the VTT captions into plain transcript text
        -> we create a Meeting + kick off the normal processing
           pipeline (chunk -> embed -> ChromaDB -> summary), exactly
           like a manual transcript upload.

Setup required in the Zoom App Marketplace (one-time, by the account
owner):
    1. Build App -> "Server-to-Server OAuth" app.
       - Scopes needed: cloud_recording:read:list_recording_files,
         cloud_recording:read:recording, meeting:read:list_past_participants
         (this last one is optional, only used to try to auto-assign
         participants by email).
       - Copy Account ID / Client ID / Client Secret into .env as
         ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET.
    2. On the same app (or a separate webhook-only app), add an event
       subscription for "All Recordings have completed" (recording.completed)
       pointing at:  https://YOUR_DOMAIN/api/webhooks/zoom
       Copy the "Secret Token" into .env as ZOOM_WEBHOOK_SECRET_TOKEN.
    3. Cloud recording + "Audio transcript" must be enabled in the
       Zoom account's recording settings, or no TRANSCRIPT file will
       exist to download.

This cannot be exercised end-to-end without a real Zoom account and a
publicly reachable HTTPS URL for Zoom to call, so treat this as the
correct, documented API contract rather than something tested live.
"""

import time

import requests

from app.config import settings

_ZOOM_OAUTH_URL = "https://zoom.us/oauth/token"

_token_cache: dict = {"access_token": None, "expires_at": 0}


def get_zoom_access_token() -> str:
    """
    Server-to-Server OAuth token, cached in-memory until ~60s before
    expiry (Zoom tokens last 1 hour).
    """

    if not (
        settings.zoom_account_id
        and settings.zoom_client_id
        and settings.zoom_client_secret
    ):
        raise ValueError(
            "Zoom is not configured. Set ZOOM_ACCOUNT_ID, "
            "ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET in the environment."
        )

    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    response = requests.post(
        _ZOOM_OAUTH_URL,
        params={
            "grant_type": "account_credentials",
            "account_id": settings.zoom_account_id,
        },
        auth=(settings.zoom_client_id, settings.zoom_client_secret),
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    _token_cache["access_token"] = data["access_token"]
    # Refresh a little early to avoid using a token that expires
    # mid-request.
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60

    return _token_cache["access_token"]


def find_transcript_file(recording_files: list[dict]) -> dict | None:
    """Zoom includes several file types per recording (MP4, M4A,
    CHAT, TRANSCRIPT, CC ...) — find the auto-generated transcript."""

    for file in recording_files:
        if file.get("file_type") == "TRANSCRIPT":
            return file

    return None


def download_transcript_vtt(download_url: str) -> str:
    """Download the transcript file's raw VTT content. Zoom recording
    download URLs require the OAuth access token as a query param."""

    token = get_zoom_access_token()

    response = requests.get(
        download_url,
        params={"access_token": token},
        timeout=60,
    )
    response.raise_for_status()

    return response.text


def vtt_to_plain_text(vtt_content: str) -> str:
    """
    Convert Zoom's WebVTT transcript into plain, readable transcript
    text, merging consecutive lines from the same speaker and
    stripping timestamps/cue numbers.

    Zoom VTT cues typically look like:

        1
        00:00:01.000 --> 00:00:04.000
        Ahmed: Let's start with the frontend update.

    """

    lines = vtt_content.splitlines()

    text_lines: list[str] = []
    last_speaker = None
    buffer: list[str] = []

    def flush():
        if buffer:
            merged = " ".join(buffer).strip()
            if merged:
                text_lines.append(merged)
            buffer.clear()

    for raw_line in lines:
        line = raw_line.strip()

        if not line or line.upper() == "WEBVTT":
            continue

        # Cue index (a bare integer) — ignore.
        if line.isdigit():
            continue

        # Timestamp line — a new cue is starting.
        if "-->" in line:
            continue

        # Actual caption text, possibly "Speaker Name: text"
        if ":" in line and len(line.split(":", 1)[0]) < 40:
            speaker, _, content = line.partition(":")
            speaker = speaker.strip()
            content = content.strip()

            if speaker != last_speaker:
                flush()
                last_speaker = speaker
                buffer.append(f"{speaker}: {content}")
            else:
                buffer.append(content)
        else:
            buffer.append(line)

    flush()

    return "\n".join(text_lines)
