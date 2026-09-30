import json
import threading
from http.server import ThreadingHTTPServer

import pytest
import requests
from app.config import settings
from .test_live_sessions import people
from setup_network import private_ipv4, prepare
import device_setup_server


@pytest.mark.parametrize('address',['127.0.0.1','0.0.0.0','8.8.8.8','169.254.1.2','::1','example.com','10.0.0.1; whoami'])
def test_setup_rejects_non_lan_address(address):
    with pytest.raises(ValueError):private_ipv4(address)


@pytest.mark.parametrize('address',['10.35.150.81','192.168.1.20','172.16.0.8'])
def test_lan_address(address):
    assert private_ipv4(address)==address


def test_device_details_admin_only_and_excludes_private_paths(client,people,tmp_path,monkeypatch):
    host,employee,_=people
    monkeypatch.setattr(settings,'data_dir',str(tmp_path))
    assert client.get('/api/conference/device-access',headers=host).json()=={'configured':False}
    folder=tmp_path/'network';(folder/'public').mkdir(parents=True)
    (folder/'config.json').write_text(json.dumps({'address':'10.35.150.81','key_file':'private/server.key'}))
    (folder/'public/meeting-brain-wifi.crt').write_bytes(b'public-certificate')
    assert client.get('/api/conference/device-access',headers=employee).status_code==403
    result=client.get('/api/conference/device-access',headers=host)
    assert result.status_code==200
    assert result.json()['app_url']=='https://10.35.150.81:8100/login'
    assert 'key_file' not in result.text and 'private/' not in result.text


def test_bootstrap_never_serves_private_files_or_accepts_login(tmp_path,monkeypatch):
    (tmp_path/'public').mkdir();(tmp_path/'private').mkdir()
    (tmp_path/'public/index.html').write_text('Setup only')
    (tmp_path/'public/meeting-brain-wifi.crt').write_bytes(b'public certificate')
    (tmp_path/'private/meeting-brain-ca.key').write_text('PRIVATE KEY MUST NOT BE SERVED')
    monkeypatch.setattr(device_setup_server,'FOLDER',tmp_path)
    server=ThreadingHTTPServer(('127.0.0.1',0),device_setup_server.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        assert requests.get(base+'/',timeout=2).text=='Setup only'
        cert=requests.get(base+'/meeting-brain-wifi.crt',timeout=2)
        assert cert.content==b'public certificate'
        assert cert.headers['X-Content-Type-Options']=='nosniff'
        for path in ['/private/meeting-brain-ca.key','/%2e%2e/private/meeting-brain-ca.key','/.env','/config.json','/users/login']:
            assert requests.get(base+path,timeout=2).status_code==404
        assert requests.post(base+'/users/login',json={'password':'not-real'},timeout=2).status_code==501
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
