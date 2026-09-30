"""Opt-in real-browser live workflow check with a separate SQLite database.

Uses synthetic accounts/media only. Real project accounts and notifications are
never touched. Requires the local Jitsi service and Chrome to be available.
"""
import base64
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
from smoke_conference import CDP

ROOT = Path(__file__).resolve().parent.parent


def wait_for(check, description, seconds=60):
    until = time.monotonic()+seconds
    while time.monotonic()<until:
        value = check()
        if value: return value
        time.sleep(.5)
    raise RuntimeError('Timed out: '+description)


def run():
    folder=ROOT/'backend'/'data'/('workflow-check-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    env=dict(os.environ, DATABASE_URL='sqlite:///'+(folder/'test.db').as_posix(),
             DATA_DIR=str(folder),WORKER_ENABLED='false',SECRET_KEY=secrets.token_hex(32),
             PYTHONPATH=str(ROOT/'backend'),TEST_PASSWORD=secrets.token_hex(20))
    seed="""
import os
from app.database import Base,engine,SessionLocal
from app.models import User
from app.security.auth import hash_password
Base.metadata.create_all(engine)
with SessionLocal() as db:
 for name,role in [('Demo Host','admin'),('Demo Employee','employee')]:
  db.add(User(name=name,email=role+'@example.com',role=role,password_hash=hash_password(os.environ['TEST_PASSWORD'])))
 db.commit()
"""
    subprocess.run([sys.executable,'-c',seed],env=env,check=True,capture_output=True)
    log=(folder/'server.log').open('w')
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port','8124'],
                            cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=flags)
    chrome=None;browser=None
    base='http://127.0.0.1:8124';debug='http://127.0.0.1:9238'
    try:
        def ready():
            try:return requests.get(base+'/login',timeout=1).ok
            except requests.RequestException:return False
        wait_for(ready,'isolated test app')
        tokens={}
        for role in ['admin','employee']:
            response=requests.post(base+'/users/login',json={'email':role+'@example.com','password':env['TEST_PASSWORD']},timeout=10)
            response.raise_for_status();tokens[role]=response.json()['access_token']
        chrome=subprocess.Popen([r'C:\Program Files\Google\Chrome\Application\chrome.exe','--headless=new',
            '--remote-debugging-port=9238','--user-data-dir='+str(folder/'chrome'),'--no-first-run',
            '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
            '--autoplay-policy=no-user-gesture-required','--window-size=1440,1000','about:blank'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
        def browser_ready():
            try:return requests.get(debug+'/json/version',timeout=1).json()
            except (requests.RequestException,ValueError):return False
        browser=CDP(wait_for(browser_ready,'test browser')['webSocketDebuggerUrl'])
        tabs={}
        for role in tokens:
            context=browser.call('Target.createBrowserContext')['browserContextId']
            target=browser.call('Target.createTarget',{'url':'about:blank','browserContextId':context})['targetId']
            item=next(t for t in requests.get(debug+'/json/list',timeout=5).json() if t['id']==target)
            tab=CDP(item['webSocketDebuggerUrl']);tabs[role]=tab
            tab.call('Page.enable')
            tab.call('Page.addScriptToEvaluateOnNewDocument',{'source':f"if(location.origin==={json.dumps(base)}) localStorage.setItem('access_token',{json.dumps(tokens[role])});"})
            tab.call('Page.navigate',{'url':base+('/live' if role=='admin' else '/dashboard')})
            wait_for(lambda:tab.evaluate("document.readyState==='complete' && location.pathname!== '/login' && location.pathname !== 'blank' && location.origin === '"+base+"'"),'authenticated page')
        host,employee=tabs['admin'],tabs['employee']
        wait_for(lambda:host.evaluate("!!document.querySelector('#meeting-title') && !document.querySelector('#create-form').hidden"),'host studio')
        host.evaluate("document.querySelector('#meeting-title').value='Product launch planning'; document.querySelector('#create-form button').click()")
        wait_for(lambda:host.evaluate("document.querySelector('#admission-status')?.textContent.includes('notified')"),'host joins and announces')
        print('PASS: Start & notify team opened the room and announced the host.',flush=True)
        wait_for(lambda:employee.evaluate("document.querySelectorAll('.live-card').length===1 && document.querySelector('#notification-count').textContent==='1'"),'employee live card and badge')
        employee.evaluate("document.querySelector('#notification-bell').click()")
        screenshot=employee.call('Page.captureScreenshot',{'format':'png'})['data']
        (ROOT/'backend/data/live-dashboard-check.png').write_bytes(base64.b64decode(screenshot))
        print('PASS: employee dashboard shows live card, unread badge and Join notification.',flush=True)
        employee.evaluate("document.querySelector('.live-card .button-primary').click()")
        wait_for(lambda:employee.evaluate("document.querySelector('#admission-status')?.textContent.includes('You’re in')"),'employee one-click join')
        print('PASS: employee joined from the dashboard without a second login.',flush=True)
        headers={'Authorization':'Bearer '+tokens['admin']}
        sessions=requests.get(base+'/api/live/',headers=headers,timeout=5).json()
        assert len(sessions)==1 and sessions[0]['attendee_count']==2
        import sqlite3
        with sqlite3.connect(folder/'test.db') as db:
            assert db.execute('SELECT count(*) FROM meetings').fetchone()[0]==0
        host.evaluate("document.querySelector('#end-meeting').click()")
        sid=sessions[0]['session_id']
        wait_for(lambda: requests.get(base+'/api/live/'+sid,headers=headers,timeout=5).json().get('ended_at'),'end closes invitations')
        assert requests.post(base+'/api/live/'+sid+'/admission',headers={'Authorization':'Bearer '+tokens['employee']},timeout=5).status_code==409
        print('PASS: title-only session created no SQL meeting; ending blocks new admissions.',flush=True)
    finally:
        if browser:
            try:browser.call('Browser.close')
            except Exception:pass
        if chrome:
            try:chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:chrome.terminate()
        server.terminate();server.wait(timeout=10);log.close()


if __name__=='__main__':run()

