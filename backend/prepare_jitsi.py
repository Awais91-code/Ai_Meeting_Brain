"""Prepare official Jitsi Docker Compose with JWT-only admission.

Does not start containers, alter the application's .env, or expose ports.
Example: python backend/prepare_jitsi.py --domain meet.company.com --advertise-ip 203.0.113.10
"""
import argparse
import re
import secrets
from pathlib import Path
import requests


def prepare(domain, advertise_ip):
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", domain) or domain.lower() == "meet.jit.si":
        raise ValueError("Supply your own hostname without https:// or a port")
    import ipaddress
    ipaddress.ip_address(advertise_ip)
    root = Path(__file__).resolve().parent / "data" / "jitsi"
    root.mkdir(parents=True, exist_ok=True)
    if (root / ".env").exists():
        raise ValueError("Jitsi is already prepared. Edit backend/data/jitsi/.env; secrets were not replaced.")
    release = requests.get("https://api.github.com/repos/jitsi/docker-jitsi-meet/releases/latest", timeout=30)
    release.raise_for_status()
    tag = release.json()["tag_name"]
    if not re.fullmatch(r"stable-[0-9-]+", tag):
        raise ValueError("The latest release is not a recognized stable release")
    response = requests.get(f"https://raw.githubusercontent.com/jitsi/docker-jitsi-meet/{tag}/docker-compose.yml", timeout=30)
    response.raise_for_status()
    (root / "docker-compose.yml").write_text(response.text, encoding="utf-8")
    config = root / "config"
    for name in ["web", "prosody/config", "prosody/prosody-plugins-custom", "jicofo", "jvb",
                 "jigasi", "jibri", "transcriber", "storage/jibri", "storage/prosody",
                 "storage/transcripts", "storage/web", "tmp/web-crontabs", "tmp/web-load-test"]:
        (config / name).mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    values = {
        "CONFIG": config.as_posix(), "HTTP_PORT": "8088", "HTTPS_PORT": "8443",
        "PUBLIC_URL": f"https://{domain}:8443", "JVB_ADVERTISE_IPS": advertise_ip,
        "TZ": "Asia/Karachi", "JITSI_IMAGE_VERSION": tag,
        "ENABLE_AUTH": "1", "AUTH_TYPE": "jwt", "ENABLE_GUESTS": "0",
        "JWT_ALLOW_EMPTY": "0", "JWT_AUTH_TYPE": "token", "JWT_TOKEN_AUTH_MODULE": "token_verification",
        "JWT_APP_ID": "meeting-brain", "JWT_APP_SECRET": secret,
        "JWT_ACCEPTED_ISSUERS": "meeting-brain", "JWT_ACCEPTED_AUDIENCES": "meeting-brain",
        "ENABLE_JAAS_COMPONENTS": "0", "ENABLE_HTTP_REDIRECT": "1",
        "JICOFO_AUTH_PASSWORD": secrets.token_hex(32), "JVB_AUTH_PASSWORD": secrets.token_hex(32),
    }
    (root / ".env").write_text("\n".join(f"{k}={v}" for k, v in values.items())+"\n", encoding="utf-8")
    app_values = {"JITSI_DOMAIN": f"{domain}:8443", "JITSI_APP_ID": "meeting-brain",
                  "JITSI_APP_SECRET": secret, "JITSI_JWT_SUBJECT": "meet.jitsi", "JITSI_REQUIRE_AUTH": "true"}
    (root / ".env.application").write_text("\n".join(f"{k}={v}" for k, v in app_values.items())+"\n", encoding="utf-8")
    print(f"Prepared {tag} in {root}. Secrets were saved locally, not printed.")
    print("Configure trusted HTTPS and copy .env.application settings into the repository root .env.")
    print("Start Docker, then run docker compose up -d from backend/data/jitsi. See deployment/JITSI.md.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--advertise-ip", required=True)
    args = parser.parse_args()
    prepare(args.domain, args.advertise_ip)
