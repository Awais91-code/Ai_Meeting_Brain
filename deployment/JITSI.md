# Employee-only video meetings

The application issues five-minute, room-specific Jitsi JWTs only to active
employees and admins. Public self-registration is disabled. Admins provision
employees from **Team members**. Share `/live/<session-id>` application links.
Do not use the public `meet.jit.si` service for restricted meetings.

## Prepare the free self-hosted server

Jitsi software is free. You still need a computer/server reachable by your team,
Docker, a hostname and trusted HTTPS. No hosted service subscription is required.
This checkout now supports a same-Wi-Fi demo. `backend/data/network/config.json`
contains the current laptop IP and HTTPS app address. The Jitsi service uses that
IP on port 8443; `JVB_ADVERTISE_IPS` uses the same reachable Wi-Fi address.
The app and Jitsi share signing credentials, guests are disabled, and Docker
services are started. A localhost-only server certificate is trusted for the
current Windows account. Open the **application**, not the raw Docker URL.
Direct Jitsi visits have no admission token and cannot use app passwords.

For a new Windows installation after `prepare_jitsi.py`, run
`./setup-local-meetings.ps1` once and restart the app. It preserves JWT secrets,
backs up original TLS files, creates a server-only localhost certificate valid
for one year, and installs only that certificate into CurrentUser's trust store.
It does not create a general certificate authority or disable TLS verification.
Renew the local certificate when it expires; public deployments should use a
publicly trusted certificate instead. Do not run this local helper on a public server.

Daily use: open Docker Desktop, then choose **Start meeting** in Meeting Brain.
The app can start this fixed Compose project when containers are stopped.
Only administrators can trigger startup; no shell commands are accepted from clients.
Employees receive automatic live cards and notifications when the host joins.

## Same-Wi-Fi phone testing

Run `./setup-network-meetings.ps1` once, then `./start.ps1`. Network setup reuses
the JWT secret, generates a separate development CA and server certificate, and
configures Jitsi's public URL and videobridge address. The CA has server-auth usage,
a zero subordinate-CA path length, and name constraints for localhost/private IPv4
ranges. Only its public certificate is offered to phones. Private keys live under
ignored `backend/data/network/private`, outside every static/file-serving root.

The Windows firewall helper only creates `MeetingBrain-WiFi-Web` (TCP 8100, 8101,
8443) and `MeetingBrain-WiFi-Media` (UDP 10000), bound to the chosen laptop IP,
network adapter, and `LocalSubnet` remote scope. It does not change global firewall
settings, router port forwarding, guest access or authentication.

Android installs the development CA once from the setup page on HTTP port 8101.
This bootstrap page contains instructions and the public certificate only; sign-in
is exclusively at the HTTPS app on 8100. The admin's **Phone setup** page displays
the certificate fingerprint for comparison. Phones must use the same Wi-Fi/hotspot,
with device isolation disabled. Android Chrome can join through the iframe; the
deep-link prompt for installing Jitsi is disabled. Laptop capture still requires
the host to share tab audio. A mobile employee does not need screen capture support.

The server certificate lasts one year; the development CA lasts two years. Network
setup refreshes the leaf and reuses the CA. If the CA expires, replace it and install
the new public CA on test devices. For public hosting, use public certificates instead.
To return to localhost-only configuration, stop the Wi-Fi server, run
`./setup-local-meetings.ps1`, then `./start.ps1 -LocalOnly`. Remove this project's
two firewall rules and the development CA from test-device trust stores when no
longer needed.

## Moving to a public server

For team deployment, edit the prepared `.env` and `.env.application` host/IP settings
instead of rerunning the preparation script (which protects existing secrets).
Clear `JITSI_CA_BUNDLE` when using a public certificate. Set `MANAGED_JITSI=false`
if the conference server is hosted separately; the app then checks its availability
without trying to control remote Docker. Both app and conference need reachable
HTTPS endpoints; allow UDP 10000 to Jitsi, with TURN where restrictive networks require it.

1. Choose the Jitsi host and its IP. The app can run separately. For a same-machine
   development test use `localhost` and `127.0.0.1`; other computers cannot use
   your localhost invite. For team use, supply a DNS hostname and reachable IP.
2. From the repository root, run:

   ```powershell
   .\.venv\Scripts\python.exe backend/prepare_jitsi.py --domain meet.your-company.com --advertise-ip YOUR_SERVER_IP
   ```

   This downloads the official stable release's Compose file, pins its image
   version, creates configuration directories and generates distinct secrets
   under ignored `backend/data/jitsi`. Reruns do not overwrite secrets. It does
   not start services or change the app's existing configuration.
3. Configure trusted HTTPS for the hostname. For publicly reachable DNS, use
   the official Docker guide's Let's Encrypt settings (DNS must resolve to the
   server and TCP 80 must reach certificate validation). Alternatively terminate
   TLS with your existing reverse proxy. The generated development ports are
   HTTPS 8443 and HTTP 8088; align `PUBLIC_URL`, `JITSI_DOMAIN`, port mappings and
   certificate/proxy configuration for your deployment. Clients also need access
   to the videobridge's UDP 10000. Docker's self-signed development certificate
   is not sufficient for a trusted embedded meeting in production.
4. With Docker running:

   ```powershell
   Set-Location backend/data/jitsi
   docker compose config --quiet
   docker compose up -d
   ```

   On Linux, ensure the storage/tmp directories are writable by the container's
   UID 1000, following the official guide for your downloaded release.
5. Copy settings from `backend/data/jitsi/.env.application` into the repository
   root `.env`, without removing existing database/AI settings. Restart the app.
   Give the FastAPI application its own reachable HTTPS URL as well, normally
   through a reverse proxy to `127.0.0.1:8100` on the app host. Employees must open
   the app at that URL: invite links use the page's origin. A `localhost` invite
   only works on the organizer's own computer.
6. Verify from a logged-out/private browser that a raw Jitsi room URL cannot join.
   Verify an app invite requires login, an active employee can join, and a disabled
   employee cannot obtain admission. Finish a recorded test call and confirm its
   attendee sees the resulting notes and chat without manual assignment.

## Required Jitsi settings

The preparation script sets:

```dotenv
ENABLE_AUTH=1
AUTH_TYPE=jwt
ENABLE_GUESTS=0
JWT_ALLOW_EMPTY=0
JWT_AUTH_TYPE=token
JWT_TOKEN_AUTH_MODULE=token_verification
JWT_APP_ID=meeting-brain
JWT_ACCEPTED_ISSUERS=meeting-brain
JWT_ACCEPTED_AUDIENCES=meeting-brain
```

`JWT_APP_SECRET` must match the app's `JITSI_APP_SECRET` (at least 32 characters).
The app uses `JITSI_JWT_SUBJECT=meet.jitsi`, matching the default XMPP domain.
`JITSI_REQUIRE_AUTH=true` confirms the operator has enabled the above settings;
the app cannot enforce a separately misconfigured conference server's rules.
It refuses to issue tokens without these app settings or for `meet.jit.si`.

JWTs are short-lived bearer credentials: forwarding a token can impersonate its
holder until expiry. Tokens are kept out of application invite URLs and returned
with `Cache-Control: no-store`. Disabling an account blocks new admissions but
does not eject an already connected Jitsi participant. Remove that participant
from the running room if immediate removal is needed.

The embedded `videoConferenceJoined` event submits a user/room-bound attendance
receipt. Attendance is idempotent and automatically becomes note access when
the transcript is committed. This browser callback is access automation, not
tamper-proof proof of physical attendance. Old manually assigned meetings remain
unchanged. New invitations expire after 24 hours and close when the host ends the
session or audio is saved. A previously issued JWT may remain valid for up to
five minutes; ending invitations is not immediate revocation of existing tokens.

## Recording and persistence

The host must grant browser audio/microphone permission and keep the recorder
page open until upload succeeds. Leaving the embedded room closes invitations
and ends the host's recording. Other app clients leave on their next status check;
this does not forcibly revoke externally reused JWTs. Closing the browser before
upload can lose unsaved audio; use the downloadable backup after capture.
After upload, disk manifests allow recovery across server restarts. A SQL meeting
is created only once a nonempty transcript has been saved, with all joined
employees in the same transaction. Failed speech recognition leaves a recoverable
draft with retry/replacement upload controls, not an empty database meeting.

References: [official Docker deployment guide](https://jitsi.github.io/handbook/docs/devops-guide/devops-guide-docker/),
[official iframe integration](https://jitsi.github.io/handbook/docs/dev-guide/dev-guide-iframe/).
