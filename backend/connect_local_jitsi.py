"""One-time localhost demo setup. Keeps existing JWT secrets and meeting data."""
import os
import shutil
import subprocess
from pathlib import Path
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "backend" / "data" / "jitsi"


def connect():
    values = dotenv_values(PROJECT / ".env")
    if len(values.get("JWT_APP_SECRET", "")) < 32:
        raise RuntimeError("Prepare Jitsi first with backend/prepare_jitsi.py.")
    openssl = shutil.which("openssl") or r"C:\Program Files\Git\usr\bin\openssl.exe"
    if not Path(openssl).exists():
        raise RuntimeError("OpenSSL is needed for one-time local HTTPS setup (included with Git for Windows).")
    keys = PROJECT / "config" / "storage" / "web" / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    cert = keys / "localhost-v2.crt"
    key = keys / "localhost-v2.key"
    if not cert.exists() or not key.exists():
        # Do not inherit the machine's openssl.cnf CA extensions.
        config = keys / "localhost.cnf"
        config.write_text("[req]\ndistinguished_name=dn\nx509_extensions=server\nprompt=no\n[dn]\nCN=localhost\n[server]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n",encoding="utf-8")
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
                        "-keyout", str(key), "-out", str(cert), "-config", str(config)], check=True, capture_output=True)
    for source, destination in [(cert, keys / "cert.crt"), (key, keys / "cert.key")]:
        if destination.exists() and not destination.with_suffix(destination.suffix + ".original").exists():
            shutil.copy2(destination, destination.with_suffix(destination.suffix + ".original"))
        shutil.copy2(source, destination)
    subprocess.run([openssl,"x509","-in",str(cert),"-outform","DER","-out",str(keys / "localhost.cer")],check=True)
    app_values = {"JITSI_DOMAIN":"localhost:8443", "JITSI_APP_ID":values["JWT_APP_ID"],
                  "JITSI_APP_SECRET":values["JWT_APP_SECRET"], "JITSI_JWT_SUBJECT":"meet.jitsi",
                  "JITSI_REQUIRE_AUTH":"true", "MANAGED_JITSI":"true", "JITSI_CA_BUNDLE":cert.as_posix()}
    for k,v in app_values.items():
        set_key(str(ROOT / ".env"),k,v,quote_mode="always")
    for k,v in {"PUBLIC_URL":"https://localhost:8443","JVB_ADVERTISE_IPS":"127.0.0.1",
                "ENABLE_AUTH":"1","AUTH_TYPE":"jwt","ENABLE_GUESTS":"0","JWT_ALLOW_EMPTY":"0"}.items():
        set_key(str(PROJECT / ".env"),k,v,quote_mode="always")
    network_config = ROOT / 'backend/data/network/config.json'
    if network_config.exists():
        network_config.replace(network_config.with_name('config.disabled.json'))
    print("Local meeting settings connected. JWT secrets were preserved and not printed.")
    print("Local certificate prepared (server-only, not a certificate authority).")


if __name__ == "__main__":
    connect()
