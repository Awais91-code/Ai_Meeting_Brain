"""Opt-in local integration check: real Chrome, real Jitsi, synthetic media/users.

Does not create application users, meetings, recordings or notifications.
Uses a dedicated temporary Chrome profile; never disables HTTPS verification.
"""
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import requests
import websocket
from app.config import settings


class CDP:
    def __init__(self, url):
        self.socket = websocket.create_connection(url, timeout=10, suppress_origin=True)
        self.sequence = 0

    def call(self, method, params=None):
        self.sequence += 1
        self.socket.send(json.dumps({'id':self.sequence,'method':method,'params':params or {}}))
        while True:
            data = json.loads(self.socket.recv())
            if data.get('id') == self.sequence:
                if 'error' in data:
                    raise RuntimeError(data['error'])
                return data.get('result',{})

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True})
        if result.get('exceptionDetails'):
            raise RuntimeError('Browser evaluation failed')
        return result.get('result',{}).get('value')


def run(app_url='http://127.0.0.1:8000', mobile=False):
    chrome = Path(os.environ.get('PROGRAMFILES','C:/Program Files')) / 'Google/Chrome/Application/chrome.exe'
    profile = Path(settings.data_dir) / ('browser-check-' + uuid.uuid4().hex)
    port = 9237
    process = subprocess.Popen([str(chrome),'--headless=new',f'--remote-debugging-port={port}',
        f'--user-data-dir={profile}','--no-first-run','--no-default-browser-check',
        '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
        '--autoplay-policy=no-user-gesture-required','about:blank'],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    browser = None
    try:
        for _ in range(50):
            try:
                version=requests.get(f'http://127.0.0.1:{port}/json/version',timeout=1).json()
                browser=CDP(version['webSocketDebuggerUrl']);break
            except (requests.RequestException, ValueError): time.sleep(.2)
        if not browser: raise RuntimeError('Chrome did not start')
        room='meetingbraincheck'+uuid.uuid4().hex
        peers=[]
        for name in ['Host check','Employee check']:
            target=requests.put(f'http://127.0.0.1:{port}/json/new?about:blank',timeout=5).json()
            tab=CDP(target['webSocketDebuggerUrl']);peers.append(tab)
            tab.call('Page.enable')
            if mobile and name == 'Employee check':
                tab.call('Emulation.setUserAgentOverride',{'userAgent':'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36'})
                tab.call('Emulation.setDeviceMetricsOverride',{'width':412,'height':915,'deviceScaleFactor':1,'mobile':True})
                tab.call('Emulation.setTouchEmulationEnabled',{'enabled':True})
            tab.call('Page.navigate',{'url':app_url.rstrip('/')+'/login'})
            for _ in range(100):
                if tab.evaluate("location.pathname === '/login' && document.readyState === 'complete'"):break
                time.sleep(.2)
            print('Test page:',tab.evaluate('location.origin + location.pathname'),flush=True)
            assert tab.evaluate('window.isSecureContext && !!navigator.mediaDevices?.getUserMedia'), 'A trusted secure context is required for microphone/camera'
            now=datetime.now(timezone.utc)
            token=jwt.encode({'iss':settings.jitsi_app_id,'aud':settings.jitsi_app_id,
                'sub':settings.jitsi_jwt_subject,'room':room,'iat':now,'nbf':now-timedelta(seconds=10),
                'exp':now+timedelta(minutes=5),'context':{'user':{'id':uuid.uuid4().hex,'name':name}}},
                settings.jitsi_app_secret,algorithm='HS256')
            options=json.dumps({'domain':settings.jitsi_domain,'room':room,'jwt':token,'name':name})
            tab.evaluate("""(() => {
                const t = OPTIONS;
                document.body.replaceChildren(); document.body.style='margin:0;height:100vh';
                window.check={joined:false,participants:0,errors:[],sdk:false};
                const script=document.createElement('script');script.src='https://'+t.domain+'/external_api.js';
                script.onerror=()=>{window.check.errors.push('sdk-load-failed');};
                script.onload=()=>{
                    window.check.sdk=true;
                    window.meeting=new JitsiMeetExternalAPI(t.domain,{roomName:t.room,jwt:t.jwt,
                        parentNode:document.body,width:'100%',height:'100%',userInfo:{displayName:t.name},
                        configOverwrite:{prejoinConfig:{enabled:false},disableDeepLinking:true,startWithVideoMuted:true}});
                    meeting.addListener('videoConferenceJoined',()=>{window.check.joined=true;});
                    meeting.addListener('participantJoined',()=>{window.check.participants++;});
                    meeting.addListener('errorOccurred',e=>{window.check.errors.push({name:e.name,type:e.type});});
                };document.head.appendChild(script);
            })()""".replace('OPTIONS',options))
        for iteration in range(60):
            states=[p.evaluate('window.check') for p in peers]
            if iteration % 10 == 0:print('Browser connection:',states,flush=True)
            if all(s and s['joined'] and s['participants'] for s in states):
                print('PASS: two token-authenticated Chrome participants joined the same private room.',flush=True)
                return
            time.sleep(1)
        screenshot=peers[0].call('Page.captureScreenshot',{'format':'png'})['data']
        import base64
        (Path(settings.data_dir)/'conference-check.png').write_bytes(base64.b64decode(screenshot))
        print('Final browser connection:',states,flush=True)
        raise RuntimeError('Conference join did not complete; see backend/data/conference-check.png')
    finally:
        if browser:
            try: browser.call('Browser.close')
            except Exception: pass
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.terminate()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-url',default='http://127.0.0.1:8000')
    parser.add_argument('--mobile',action='store_true')
    args=parser.parse_args()
    run(args.app_url,args.mobile)
