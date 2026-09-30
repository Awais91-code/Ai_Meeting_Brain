from app.database import SessionLocal
from app.models import Meeting, Notification, User
from app.services import live_sessions, conference
from app.config import settings
from .test_live_sessions import people, draft


def test_host_join_announces_once_to_active_employees(client, people):
    host, attendee, other = people
    with SessionLocal() as db:
        db.query(User).filter_by(email="other@example.com").first().is_active = False
        db.commit()
    sid = draft(client, host)
    assert client.get('/api/live/',headers=attendee).json() == []
    assert client.get('/api/notifications/',headers=attendee).json() == []
    ticket = client.post(f'/api/live/{sid}/admission',headers=host).json()
    for _ in range(2):
        response = client.post(f'/api/live/{sid}/joined',headers=host,json={'receipt':ticket['receipt']})
        assert response.status_code == 200, response.text
    live_sessions.recover_announcements()
    cards = client.get('/api/live/',headers=attendee).json()
    assert cards[0]['is_live'] and cards[0]['organizer'] == 'Host'
    messages = client.get('/api/notifications/',headers=attendee).json()
    assert len(messages) == 1 and messages[0]['join_available']
    assert messages[0]['meeting_id'] is None and messages[0]['live_session_id'] == sid
    with SessionLocal() as db:
        assert db.query(Meeting).count() == 0
        assert db.query(Notification).count() == 1
    assert client.patch(f"/api/notifications/{messages[0]['id']}/read",headers=host).status_code == 404
    assert client.post(f'/api/live/{sid}/end',headers=attendee).status_code == 403
    assert client.post(f'/api/live/{sid}/end',headers=host).status_code == 200
    assert client.get('/api/notifications/',headers=attendee).json()[0]['join_available'] is False
    assert client.post(f'/api/live/{sid}/admission',headers=attendee).status_code == 409
    assert client.get('/api/live/',headers=attendee).json() == []


def test_recover_start_after_notification_failure(client, people):
    host, attendee, _ = people
    sid = draft(client,host)
    from datetime import datetime, timezone
    with live_sessions.edit_session(sid) as data:
        data['started_at'] = datetime.now(timezone.utc).isoformat()
    live_sessions.recover_announcements()
    live_sessions.recover_announcements()
    assert len(client.get('/api/notifications/',headers=attendee).json()) == 1


def test_service_control_is_admin_only_and_never_takes_commands(client, people, monkeypatch):
    host, attendee, _ = people
    assert client.get('/api/conference/status').status_code in (401,403)
    assert client.post('/api/conference/start',headers=attendee).status_code == 403
    monkeypatch.setattr(settings,'managed_jitsi',True)
    monkeypatch.setattr(conference,'status',lambda:{'state':'offline'})
    monkeypatch.setattr(conference,'start',lambda:{'state':'starting'})
    assert client.post('/api/conference/start',headers=host).json()['state']=='starting'
    monkeypatch.setattr(settings,'jitsi_require_auth',False)
    assert client.post('/api/conference/start',headers=host).status_code == 503


def test_health_keeps_tls_verification(client, people, monkeypatch):
    import requests
    monkeypatch.setattr(conference,'_cached',(0,None))
    monkeypatch.setattr(settings,'jitsi_ca_bundle','')
    def request(url,**options):
        assert options['verify'] is True and options['allow_redirects'] is False
        raise requests.exceptions.SSLError()
    monkeypatch.setattr(conference.requests,'get',request)
    assert conference.status()['state']=='certificate_error'


def test_managed_start_uses_fixed_project_and_no_shell(client, people, monkeypatch):
    calls=[]
    monkeypatch.setattr(conference.subprocess,'run',lambda command,**kwargs:calls.append((command,kwargs)))
    conference._start()
    command, options=calls[0]
    assert command[:3]==['docker','compose','--project-directory']
    assert command[-2:]==['up','-d'] and command[3].endswith('jitsi')
    assert 'shell' not in options and options['timeout']==90
