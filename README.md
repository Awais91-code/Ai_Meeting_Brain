# AI Meeting Brain

FastAPI + SQLAlchemy/PostgreSQL (or SQLite), Jinja/Alpine UI, meeting recording,
local Whisper transcription, transcript retrieval and AI chat.

## Run this checkout

The project uses the root `.venv`, not the old `backend/venv` (which referred to
a Python installation on another path). The root `.env` contains your existing
database and AI settings. Existing accounts and meetings are preserved.

```powershell
.\start.ps1
```

After Wi-Fi setup, use the **HTTPS Wi-Fi address printed by the script** and an
existing admin account. The script also starts the Android certificate setup page.
Without Wi-Fi setup, open **http://127.0.0.1:8100/login**.
`start.ps1 -Port 8102` selects another port. Keep the terminal/server running.
The script applies database migrations before starting the app. In Wi-Fi mode it
uses port 8100; `-LocalOnly` selects the older loopback HTTP mode. If the older
development server on port 8000 is running, it remains the recovery worker and
the Wi-Fi frontend avoids starting a duplicate worker.

## Record an actual meeting

1. Provision employee accounts in **Team members**. Public signup is disabled.
2. On this computer, Wi-Fi conferencing is configured. Keep Docker Desktop running;
   you do not need to open its Jitsi URL or enter a separate Jitsi password.
   On a fresh Windows setup, run `./setup-local-meetings.ps1` once after preparing
   Jitsi. This connects existing secrets and trusts a localhost-only server
   certificate for the current Windows account. See [deployment/JITSI.md](deployment/JITSI.md).
3. In **Live sessions**, enter a title, choose **English**, **Urdu**, **Hindi** or
   **Mixed English / Urdu / Hindi**, and optionally enter names/technical terms.
   This creates a recoverable disk draft, **not a database meeting**.
4. Choose **Start & notify team**. The app starts the configured meeting containers
   if needed and opens the room. When the host joins, all active employees receive
   an in-app notification and a live card on their dashboard (within about 5 seconds).
   Employees click **Join meeting**; access to saved notes is automatic. Use an
   phone or another computer on the same Wi-Fi for the employee (see below).
5. The organizer uses **Chrome or Edge**, on localhost or HTTPS. Click **Start audio
   capture**, choose the meeting tab, enable **Share tab audio**, and allow the
   microphone. Use headphones and inform participants about recording.
6. Leave the embedded room, stop sharing, or click **Finish & save**. Keep the page
   open until upload completes. Transcription runs locally; once successful, the
   transcript and attendee access are saved to SQL together, followed by indexing,
   notes and chatbot readiness. Open **transcript & chat**.

Uploads also work without conferencing configured. A title-only or failed/silent
recording does not create a database meeting. Existing historic records are
preserved. The **Add a transcript** forms now require and save the transcript in
one request. You can resume unfinished sessions from **Live sessions**; failed
transcription supports retrying saved audio or uploading a replacement.

**End meeting**, **Finish & save**, or the host leaving closes new invitations and
saves any active capture. Other open app clients disconnect on their next status
check. For a meeting in another tab, use **Finish & save**. Browsers
require capture permission; closing the recorder before upload can lose unsaved
audio. After capture, failed uploads offer retry and a downloadable backup.

The dashboard includes live attendee counts, elapsed meeting time, notification
history, unread badges, and a recording timer. Title-only drafts still do not
create SQL meeting records. Notifications have their own independent records.

### Employee on an Android phone (same Wi-Fi / hotspot)

1. Connect both devices to the same Wi-Fi, or connect the laptop to the phone hotspot.
2. The one-time laptop setup is `./setup-network-meetings.ps1`. It detects the Wi-Fi
   address (or accepts `-IPAddress`), configures private HTTPS and Jitsi's media IP,
   and requests Windows administrator approval for app-specific local-subnet firewall
   rules. It does not open the whole firewall or enable guest meeting access.
3. Run `./start.ps1`. Keep it and Docker Desktop running. On the laptop, use
   **Phone setup** in the sidebar to copy the phone setup and HTTPS login addresses.
4. On Android, open the HTTP setup address shown there, download the certificate,
   and install it through **Settings → Security → Encryption & credentials →
   Install a certificate → CA certificate** (wording varies by phone). Compare the
   SHA-256 fingerprint with the laptop page first. This trust step is required
   once so Chrome can use the camera and microphone over local HTTPS.
5. Open the **HTTPS** app address on the phone, sign in as an employee, and tap
   **Join meeting** when the host starts. Allow camera/microphone permissions.
   No native Jitsi app is needed. Keep the Chrome meeting tab in the foreground.

Use headphones or separate rooms to avoid feedback. Record from the laptop using
**Start audio capture** and **Share tab audio**; the phone contributes its own mic
and camera. The ordinary notification, attendance, transcript and chat flow is unchanged.

If the laptop changes networks or IP addresses, rerun the network setup and restart
the app. The same local CA is reused, so the phone generally does not need a new
installation. Remove the development CA from Android's **Trusted credentials → User**
after testing. The HTTP setup server only serves a fixed public page and public
certificate; it cannot serve private keys, project files, API requests or passwords.

The setup is for the **same local network**. Remote employees on different networks
still need public HTTPS hosting and reachable media/TURN configuration; see the
deployment guide. No router ports or public tunnels were opened.

## How automatic updates work

```text
Employee admission → joined event → attendee list in disk session manifest
Browser audio → durable audio + pending disk manifest
  → multilingual Whisper → saved transcript
  → atomic SQL meeting + transcript + attendee access
  → SQL chunks + optional vectors → notes → ready → notifications
  → chatbot retrieves current meeting evidence on every question
```

A poller recovers both pending disk recordings and SQL processing jobs after a
restart. Atomic files, per-session processing locks and unique source IDs prevent
duplicate meetings after retries or crashes. A cached transcript avoids repeating
speech recognition when a later database/AI step fails. Webhook transcripts enter
SQL directly because their text is already available.

Supported deployment: **one host, shared persistent DATA_DIR, one Uvicorn worker**.
Back up SQL, `backend/data` (including session manifests/audio) and Chroma together.
Protect the data folder as it contains meeting recordings. An upload interrupted
before its manifest commit must be retried by the browser. Once a transcript is
saved, downstream failures can be retried with **Reprocess** in the meeting page.

## Chat configuration

### Answers and meeting notes

Short factual questions now default to a direct answer: for example, “What is
the budget?” returns the supported amount and relevant qualification, without
unrequested campaign dates or expense lists. Ask for a “breakdown”, “details”,
or “all action items” when you want a longer response. Search rewrites are used
only to retrieve evidence; the original question controls the answer's scope.

The meeting page formats existing Markdown summaries into labeled sections and
shows structured action items in a separate tab. Chat formats bold text, lists,
and compact citations without interpreting model-generated HTML. These display
improvements apply to existing notes without reprocessing or altering them.

The light workspace includes shared navigation, meeting search/status filters,
notes alongside chat, and responsive login/recording/admin/team screens.

Additional checks:

```powershell
node backend/tests/test_presentation.js
.\.venv\Scripts\python.exe backend/check_answer_quality.py
```

The second command sends synthetic budget evidence to the configured provider
and checks that a factual answer stays concise and no budget allocations are
invented. The optional `backend/preview_design.py` serves isolated sample data
at port 8103 for visual QA; it never changes the configured application database.

| Setting | Behavior |
| --- | --- |
| `LLM_PROVIDER=auto` | Uses the configured OpenRouter key; otherwise shows matching transcript excerpts. |
| `CHAT_MODEL=openrouter/free` | Uses OpenRouter's free model router. Availability and rate limits can vary. |
| `LLM_PROVIDER=ollama` | Generates locally using `OLLAMA_MODEL` and `OLLAMA_URL`. |
| `LLM_PROVIDER=extractive` | No generation/network calls; labels exact matching evidence as excerpts. |
| `EMBEDDING_PROVIDER=local` | Offline lexical vectors and SQL term ranking; this is not semantic embedding AI. |
| `EMBEDDING_PROVIDER=ollama` | Semantic search using your installed `EMBEDDING_MODEL`. |
| `EMBEDDING_PROVIDER=openrouter` | Semantic search using your configured provider/model; check its pricing. |

Chat uses current SQL evidence even if Chroma or an embedding API is unavailable.
It includes source excerpts, keeps each user's conversation separate, resolves
follow-ups, and distinguishes uncertain claims from confirmed decisions. Small
meetings fit in full context; long meetings use selected passages, so broad
answers may not cover every detail. Model answers still need checking against
the displayed sources. Previous assistant answers are not treated as evidence.

For free **local generation and semantic embeddings**, install
[Ollama](https://docs.ollama.com/quickstart), then:

```powershell
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

Set `LLM_PROVIDER=ollama`, `EMBEDDING_PROVIDER=ollama`,
`EMBEDDING_MODEL=nomic-embed-text` in the root `.env`, restart the server and
reprocess existing meetings. These models need disk space/RAM and download once.
The default local lexical mode works without model downloads for retrieval.

### English, Urdu and Hindi speech

`WHISPER_MODEL=small` is the multilingual CPU default, replacing `base`. Models
are downloaded once with `backend/prepare_models.py`. Larger multilingual models
such as `medium` or `large-v3` can be configured when sufficient CPU time/RAM is
available; do not use `.en` models for Urdu/Hindi. Automatic mode detects language
per segment; a dominant-language selection can help avoid Urdu/Hindi script
confusion. Recognition preserves the spoken language rather than translating it.

Capture uses 48 kHz audio and requests 128 kbps Opus, mixes the mic/tab with headroom
and compression, and applies microphone echo/noise processing. Whisper uses beam
search, conservative silence trimming and repetition/silence safeguards. Optional
vocabulary hints help names and technical terms; they are hints, not guaranteed
spellings. Quality still depends on clear audio, accents, overlap and model size.
Review names, money and dates against the recording. Whisper provides timestamps,
**not speaker identification** in mixed audio.

Notes and generated chat answers support English, Urdu/Roman Urdu and Hindi.
Unicode text and right-to-left display are preserved. With generation unavailable,
the offline fallback only matches literal transcript terms; cross-language answers
need a multilingual AI provider. Long mixed-language meetings benefit from a
multilingual semantic embedding provider because default local vectors are lexical.

## Fresh installation

Python 3.11 or 3.12 is recommended.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item backend/.env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Put that random value in `SECRET_KEY`. Set `DATABASE_URL` to your PostgreSQL
database. For a local SQLite installation, use e.g.
`DATABASE_URL=sqlite:///meeting-brain.sqlite3` and always run from the root.
The `.env` must be at the repository root; never commit it.

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe backend/create_admin.py
.\.venv\Scripts\python.exe backend/prepare_models.py
.\start.ps1
```

The model-preparation step downloads Whisper into `backend/data/models`; after
that, transcription runs locally. `.env` changes require a server restart.
The initial admin script prompts for credentials and never resets existing users.

## Optional Zoom / automation ingestion

The existing Zoom integration remains available at `POST /api/webhooks/zoom`.
Configure the Zoom OAuth credentials and secret token from `.env.example`.
Subscribe to **recording.transcript_completed** (also accepts
`recording.completed` when a transcript is already included). A meeting-ended
event alone does not contain a transcript. Zoom cloud recording requires a
licensed paid account; it is not the free path described above.

For an external automation tool, set `N8N_WEBHOOK_SECRET` and POST to
`/api/webhooks/n8n/meetings` with header `X-Webhook-Secret`:

```json
{
  "source": "your-transcription-tool",
  "external_id": "unique-meeting-recording-id",
  "title": "Planning",
  "meeting_date": "2026-09-16T10:00:00Z",
  "transcript": "Ayesha: The deadline is Friday.",
  "organizer_email": "existing-admin@example.com",
  "participant_emails": ["existing-employee@example.com"]
}
```

Use a stable `external_id` for retries. Repeated deliveries return the original
meeting rather than modifying it. Use the transcript edit endpoint for corrections.
Without an external ID, exact payload duplicates are detected. This endpoint
does not itself obtain a transcript from arbitrary meeting services.
Zoom downloads currently occur in the webhook handler; the sender must retry a
failed/timeout delivery. Browser recordings persist before any AI calls.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
node --check backend/app/static/js/capture.js
node backend/tests/test_capture.js
node backend/tests/test_presentation.js
.\.venv\Scripts\python.exe backend/check_ai.py
.\.venv\Scripts\python.exe backend/smoke_audio.py
```

The ordinary tests isolate SQL, Chroma and uploads and avoid external AI calls.
`check_ai.py` calls the configured model with synthetic facts. `smoke_audio.py`
downloads a public faster-whisper test clip and runs actual audio → upload →
Whisper → SQL/Chroma → chat in an isolated SQLite database under `backend/data/smoke`.
It does not add test meetings/accounts to your PostgreSQL database.

For a real multilingual speech smoke check, run
`python backend/check_languages.py --language ur` (or `--language hi`). This
opt-in tool downloads a public [Google FLEURS](https://huggingface.co/datasets/google/fleurs)
sample (CC BY 4.0), checks native-script output and saves its transcript/reference
and sample word error rate under `backend/data/language-check`. A single sample
is not an accuracy guarantee. The remote dataset preview may be unavailable;
the application itself does not depend on it.


### References

- [Jitsi JWT authentication and deployment](https://jitsi.github.io/handbook/docs/devops-guide/devops-guide-docker/#authentication-using-jwt-tokens)
- [Jitsi conference events](https://jitsi.github.io/handbook/docs/dev-guide/dev-guide-iframe-events/)
- [Browser audio-capture requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia)
- [Whisper local CPU transcription](https://github.com/SYSTRAN/faster-whisper)
- [Zoom cloud-recording requirements](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0062627)
