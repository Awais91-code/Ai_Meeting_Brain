"""Prepare HTTPS for a private Wi-Fi demo without changing users or JWT secrets.

Only the public CA certificate is copied into the phone setup folder. The CA
and server private keys stay outside all web roots and are never returned by APIs.
"""
import argparse
import hashlib
import ipaddress
import json
import socket
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))


def private_ipv4(value):
    address = ipaddress.ip_address(value)
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError('Use the laptop Wi-Fi IPv4 address (10.x, 172.16–31.x, or 192.168.x).')
    return str(address)


def current_private_ipv4():
    """Detect the IPv4 address used by the laptop's current default route.

    UDP connect does not send traffic; it simply asks the OS which interface it
    would use. This works on ordinary Wi-Fi and when the laptop is connected to
    a phone hotspot. Hostname addresses are a fallback for offline/private LANs.
    """
    candidates = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        candidates.append(sock.getsockname()[0])
    except OSError:
        pass
    finally:
        sock.close()

    try:
        candidates.extend(
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        )
    except OSError:
        pass

    seen = set()
    for value in candidates:
        if value in seen:
            continue
        seen.add(value)
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if (
            any(address in network for network in PRIVATE_NETWORKS)
            and not address.is_loopback
            and not address.is_link_local
        ):
            return str(address)
    raise RuntimeError(
        "Could not detect a private Wi-Fi/hotspot IPv4 address. Connect the laptop "
        "to Wi-Fi or the phone hotspot and start the app again."
    )


def existing_metadata(root=ROOT):
    path = root / 'backend/data/network/config.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        private_ipv4(data['address'])
        return data
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def prepare(address, root=ROOT):
    address = private_ipv4(address)
    previous = existing_metadata(root)
    project = root / 'backend/data/jitsi'
    values = dotenv_values(project / '.env')
    if len(values.get('JWT_APP_SECRET', '')) < 32:
        raise RuntimeError('Prepare the private Jitsi service first.')
    openssl = shutil.which('openssl') or r'C:\Program Files\Git\usr\bin\openssl.exe'
    if not Path(openssl).is_file():
        raise RuntimeError('OpenSSL is needed for setup (included with Git for Windows).')
    folder = root / 'backend/data/network'
    tls = folder / 'private'
    public = folder / 'public'
    tls.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    def run(*args):
        return subprocess.run([openssl, *map(str,args)],check=True,capture_output=True)
    ca, ca_key = tls / 'meeting-brain-ca.pem', tls / 'meeting-brain-ca.key'
    if not ca.exists() or not ca_key.exists():
        config = tls / 'ca.cnf'
        config.write_text('''[req]
distinguished_name=dn
x509_extensions=ca
prompt=no
[dn]
CN=Meeting Brain Wi-Fi Development CA
[ca]
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
nameConstraints=critical,permitted;DNS:localhost,permitted;IP:127.0.0.0/255.0.0.0,permitted;IP:10.0.0.0/255.0.0.0,permitted;IP:172.16.0.0/255.240.0.0,permitted;IP:192.168.0.0/255.255.0.0
''',encoding='utf-8')
        run('req','-x509','-newkey','rsa:3072','-nodes','-days','730','-keyout',ca_key,'-out',ca,'-config',config)
    key, leaf, chain = tls/'server.key', tls/'server.pem', tls/'server-chain.pem'
    config = tls / 'server.cnf'
    config.write_text(f'''[req]
distinguished_name=dn
prompt=no
[dn]
CN=Meeting Brain Wi-Fi
[server]
subjectAltName=DNS:localhost,IP:127.0.0.1,IP:{address}
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
''',encoding='utf-8')
    csr = tls / 'server.csr'
    run('req','-new','-newkey','rsa:2048','-nodes','-keyout',key,'-out',csr,'-config',config)
    run('x509','-req','-in',csr,'-CA',ca,'-CAkey',ca_key,'-CAcreateserial','-out',leaf,
        '-days','365','-sha256','-extfile',config,'-extensions','server')
    run('verify','-CAfile',ca,'-verify_ip',address,leaf)
    chain.write_bytes(leaf.read_bytes()+ca.read_bytes())
    der = public / 'meeting-brain-wifi.crt'
    run('x509','-in',ca,'-outform','DER','-out',der)
    fingerprint = ':'.join(f'{b:02X}' for b in hashlib.sha256(der.read_bytes()).digest())
    keys = project/'config/storage/web/keys'
    keys.mkdir(parents=True,exist_ok=True)
    shutil.copy2(chain,keys/'cert.crt')
    shutil.copy2(key,keys/'cert.key')
    for name,value in {'PUBLIC_URL':f'https://{address}:8443','JVB_ADVERTISE_IPS':address,
                       'ENABLE_AUTH':'1','AUTH_TYPE':'jwt','ENABLE_GUESTS':'0','JWT_ALLOW_EMPTY':'0',
                       'DISABLE_DEEP_LINKING':'1'}.items():
        set_key(str(project/'.env'),name,value,quote_mode='always')
    for name,value in {'JITSI_DOMAIN':f'{address}:8443','JITSI_APP_ID':values['JWT_APP_ID'],
                       'JITSI_APP_SECRET':values['JWT_APP_SECRET'],'JITSI_REQUIRE_AUTH':'true',
                       'JITSI_JWT_SUBJECT':'meet.jitsi','MANAGED_JITSI':'true','JITSI_CA_BUNDLE':ca.as_posix()}.items():
        set_key(str(root/'.env'),name,value,quote_mode='always')
    metadata = {'address':address,'app_url':f'https://{address}:8100',
                'setup_url':f'http://{address}:8101','certificate_sha256':fingerprint,
                'certificate_file':str(chain.resolve()),'key_file':str(key.resolve())}
    (folder/'config.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    # The setup page contains no login form. Credentials are entered only over HTTPS.
    (public/'index.html').write_text(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect your phone · Meeting Brain</title><style>
body{{font:16px/1.65 system-ui,sans-serif;background:#edf7f3;color:#173b32;margin:0;padding:24px}}main{{max-width:650px;margin:4vh auto;padding:30px;background:white;border-radius:22px;box-shadow:0 15px 60px #173b3212}}h1{{font-size:28px;line-height:1.2}}li{{margin:14px 0}}a{{color:#087f70}}.button{{display:inline-block;background:#087f70;color:white;padding:12px 20px;border-radius:10px;text-decoration:none}}code{{overflow-wrap:anywhere;font-size:12px}}small{{color:#536d65}}</style></head><body><main>
<p>MEETING BRAIN · PHONE SETUP</p><h1>Join from your Android phone.</h1><p>Keep the phone and laptop on the same Wi-Fi, or connect the laptop to your phone’s hotspot.</p>
<ol><li><a href="/meeting-brain-wifi.crt" download>Download the Meeting Brain Wi-Fi certificate</a>.</li>
<li>In Android <strong>Settings</strong>, search for <strong>Install a certificate</strong>. Choose <strong>CA certificate</strong> (not Wi-Fi certificate), confirm with your phone PIN, and select the downloaded file. The menu is usually under Security → Encryption &amp; credentials. Samsung may place it under More security settings.</li>
<li>Return to Chrome and open the secure app below. Sign in with your <strong>employee account</strong>. When the admin starts a meeting, tap <strong>Join meeting</strong> and allow camera and microphone access.</li></ol>
<p><a class="button" href="{metadata['app_url']}/login">Open Meeting Brain →</a></p>
<p>This is a development certificate for this private test network. Android may display a network-monitoring warning when you install a CA. Compare the SHA-256 fingerprint below with the laptop’s Phone setup page before installing it. Do not install a certificate from an unexpected source.</p>
<details><summary>Certificate fingerprint</summary><code>{fingerprint}</code></details>
<p><small>This setup page uses HTTP only to provide instructions and the public certificate. It never asks for your password. Sign in only at the HTTPS app address.</small></p>
<details><summary>Troubleshooting &amp; removal</summary><p>If the app cannot load, disable a VPN temporarily, check both devices are on the same network, and avoid guest Wi-Fi with device isolation. A phone hotspot often works well.</p><p>If Chrome still shows a certificate error, close and reopen Chrome after installation. Do not use browser security bypass flags.</p><p>After testing, remove “Meeting Brain Wi-Fi Development CA” from Android’s Trusted credentials → User section. Meeting Brain now refreshes the laptop IP automatically each time the app starts.</p></details>
</main></body></html>''',encoding='utf-8')
    if not previous or previous.get('address') != address:
        # The JVB advertises the laptop address inside Docker. Force the next
        # meeting-service start to recreate containers after a network change.
        (folder / 'jitsi-reconfigure.flag').write_text(address, encoding='utf-8')
    print('Wi-Fi settings prepared. Employee login:',metadata['app_url']+'/login')
    print('Android setup:',metadata['setup_url'])
    print('CA SHA-256:',fingerprint)
    return metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--ip')
    group.add_argument('--auto', action='store_true')
    args = parser.parse_args()
    address = args.ip if args.ip else current_private_ipv4()
    current = existing_metadata()
    folder = ROOT / 'backend/data/network'
    if (
        current
        and current.get('address') == private_ipv4(address)
        and Path(current.get('certificate_file', '')).is_file()
        and Path(current.get('key_file', '')).is_file()
    ):
        print('Wi-Fi settings already match current laptop address:', address)
        print('Employee login:', current['app_url'] + '/login')
        print('Android setup:', current['setup_url'])
    else:
        prepare(address)
