"""Opt-in real speech/provider smoke test, isolated from the application's DB.

Downloads the public faster-whisper JFK test clip and transcribes it with the
configured model. The generated index/database remain in backend/data/smoke.
"""
import os
import uuid
from pathlib import Path
import requests

folder = Path(__file__).resolve().parent / "data" / "smoke"
folder.mkdir(parents=True, exist_ok=True)
audio = folder / "jfk.flac"
if not audio.exists():
    response = requests.get("https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/tests/data/jfk.flac", timeout=60)
    response.raise_for_status()
    audio.write_bytes(response.content)

test_db = folder / ("smoke-" + uuid.uuid4().hex[:8] + ".sqlite3")
os.environ["DATABASE_URL"] = "sqlite:///" + str(test_db)
os.environ["CHROMA_DB_PATH"] = str(folder / "chroma")
os.environ["WORKER_ENABLED"] = "false"
os.environ["DEBUG"] = "false"

from fastapi.testclient import TestClient
from app.database import Base, engine, SessionLocal
from app.models import User, Meeting, TranscriptChunk
from app.security.auth import hash_password
from app.main import app
from app.services.transcription import transcribe_audio, whisper_model
from app.config import settings

# Reuse installed model weights, but isolate ALL mutable queue/audio state.
# Otherwise the live server's recovery worker could discover a test manifest.
whisper_model()
settings.data_dir = str(folder)

Base.metadata.create_all(engine)
with SessionLocal() as db:
    if not db.query(User).filter_by(email="smoke@example.com").first():
        db.add(User(name="Smoke Test", email="smoke@example.com", role="admin",
                    password_hash=hash_password("isolated-smoke-test-only")))
        db.commit()

# Decode FLAC into the WAV format accepted by the recording endpoint.
import av
container = av.open(str(audio))
wav = folder / "jfk.wav"
with av.open(str(wav), mode="w") as output:
    stream = output.add_stream("pcm_s16le", rate=16000)
    stream.layout = "mono"
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    for frame in container.decode(audio=0):
        for converted in resampler.resample(frame):
            for packet in stream.encode(converted):
                output.mux(packet)
    for packet in stream.encode(None):
        output.mux(packet)
container.close()

with TestClient(app) as client:
    token = client.post('/users/login', json={'email':'smoke@example.com', 'password':'isolated-smoke-test-only'}).json()['access_token']
    headers = {'Authorization':f'Bearer {token}'}
    session_id = client.post('/api/live/', headers=headers, json={'title':'Real audio smoke test', 'language':'en'}).json()['session_id']
    with wav.open('rb') as recording:
        result = client.post(f'/api/live/{session_id}/audio', headers=headers, files={'audio':('jfk.wav',recording,'audio/wav')})
    assert result.status_code == 200, result.text
    meeting_id = client.get(f'/api/live/{session_id}', headers=headers).json()['meeting_id']
    meeting = client.get(f'/api/meetings/{meeting_id}', headers=headers).json()
    assert meeting['status'] == 'ready', meeting.get('processing_error')
    assert 'country' in meeting['transcript'].lower(), meeting['transcript']
    reply = client.post(f'/api/meetings/{meeting_id}/ask', headers=headers,
                        json={'question':'What does the speaker ask Americans to do for their country?'})
    assert reply.status_code == 200, reply.text
    assert reply.json()['sources']
    assert 'country' in reply.json()['answer'].lower(), reply.json()['answer']
    print('PASS: real audio -> saved recording -> Whisper transcript -> SQL/Chroma -> chatbot sources and answer')
    print('Answer mode:', 'extractive' if 'AI generation is unavailable' in reply.json()['answer'] else 'generative')
    print('Isolated test database:', test_db)
