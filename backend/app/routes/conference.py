from fastapi import APIRouter, Depends, HTTPException
from app.config import settings
from app.security.auth import get_current_user, require_role
from app.services import conference
import json
import hashlib
import ipaddress
from pathlib import Path

router = APIRouter(prefix="/api/conference", tags=["Meeting service"])


@router.get("/device-access")
def device_access(user=Depends(require_role("admin"))):
    folder = Path(settings.data_dir) / 'network'
    try:
        data = json.loads((folder/'config.json').read_text(encoding='utf-8'))
        address = ipaddress.IPv4Address(data['address'])
        if not address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError('Invalid Wi-Fi address')
        fingerprint = ':'.join(f'{b:02X}' for b in hashlib.sha256((folder/'public/meeting-brain-wifi.crt').read_bytes()).digest())
        return {
            'configured': True,
            'address': str(address),
            'app_url': f'https://{address}:8100/login',
            'setup_url': f'http://{address}:8101',
            'certificate_sha256': fingerprint,
            'auto_detected': True,
        }
    except FileNotFoundError:
        return {'configured':False}
    except (ValueError, KeyError):
        raise HTTPException(503,'Phone access configuration needs to be refreshed on the laptop.')


@router.get("/status")
def status(user=Depends(get_current_user)):
    return conference.status()


@router.post("/start")
def start(user=Depends(require_role("admin"))):
    if not conference.configured():
        raise HTTPException(503, "Complete the one-time meeting service setup first.")
    if not settings.managed_jitsi:
        raise HTTPException(409, "This meeting server is managed externally.")
    if conference.status()["state"] == "ready":
        return conference.status()
    return conference.start()
