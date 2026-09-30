"""Isolated visual QA fixture. Never writes to the configured application DB."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

root = Path(__file__).resolve().parent / 'data' / 'design-preview'
root.mkdir(parents=True, exist_ok=True)
os.environ['DATABASE_URL'] = 'sqlite:///' + str(root / (uuid.uuid4().hex + '.sqlite3'))
os.environ['CHROMA_DB_PATH'] = str(root / 'chroma')
os.environ['DATA_DIR'] = str(root)
os.environ['WORKER_ENABLED'] = 'false'
os.environ['LLM_PROVIDER'] = 'extractive'
os.environ['SECRET_KEY'] = 'isolated-design-preview-key-not-for-deployment'

from app.database import Base, engine, SessionLocal
from app.models import User, Meeting, ChatMessage, TranscriptChunk
from app.security.auth import hash_password

SUMMARY = '''**Meeting Summary: Product Launch Finalization**

**Main Topics Discussed**
* Product launch schedule confirmation
* Marketing campaign timeline
* Database migration status
* Budget approval

**Important Decisions**
* Product launch date set for **Friday**.
* Marketing campaign start date set for **Wednesday** (two days prior to launch).
* Approved budget confirmed at **$50,000**.

**Important Deadlines**
* **Wednesday:** Marketing campaign begins.
* **Thursday:** Database migration expected completion (Migration Team).
* **Friday:** Product launch (Engineering Team).

**Important Responsibilities**
* **Engineering Team:** Execute product launch on Friday.
* **Marketing Team:** Initiate campaign on Wednesday.
* **Migration Team:** Complete database migration by Thursday.'''
TRANSCRIPT = 'The approved marketing budget is $1,000. It covers tools and utility bills. No amounts have been assigned to individual categories. The campaign deadline is 20 September 2026.'
Base.metadata.create_all(engine)
with SessionLocal() as db:
    admin = User(name='Ayesha Khan', email='design@example.com', role='admin', password_hash=hash_password('design-preview-only'))
    db.add(admin)
    db.flush()
    for index, (title, status) in enumerate([('Product launch finalization','ready'), ('Restaurant marketing strategy','ready'), ('Weekly engineering sync','processing'),('Customer experience review','ready'),('Design team catch-up','uploaded'),('Q4 planning workshop','ready')]):
        transcript = TRANSCRIPT if index == 1 else 'The approved launch budget is $50,000. Launch is Friday. Marketing begins Wednesday.'
        meeting = Meeting(title=title, meeting_date=datetime.now(timezone.utc)-timedelta(days=index), duration_minutes=30+index*5, organizer_id=admin.id, status=status, transcript=transcript, summary=SUMMARY if index == 0 else 'Overview\nThe team aligned on the campaign and approved the marketing budget.\n\nDecisions\n- The total marketing budget is $1,000.\n\nDeadlines\n- Campaign deadline: 20 September 2026.', action_items=json.dumps([{'task':'Prepare the launch campaign','assigned_to':'Marketing Team','deadline':'Wednesday','status':'Pending'}]))
        db.add(meeting)
        db.flush()
        db.add(TranscriptChunk(meeting_id=meeting.id, chunk_index=0, content=transcript))
        if index == 0:
            sources=[{'label':'Source 1','meeting_id':meeting.id,'chunk_index':0,'content':transcript}]
            db.add_all([ChatMessage(meeting_id=meeting.id,user_id=admin.id,role='user',content='What is the approved budget?'), ChatMessage(meeting_id=meeting.id,user_id=admin.id,role='assistant',content='The approved launch budget is $50,000. [Source 1]',sources_json=json.dumps(sources))])
    db.commit()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=8103)
