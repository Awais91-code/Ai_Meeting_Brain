# One-time setup for a demo on this Windows account and computer.
# Trusts only our localhost server certificate, not a general certificate authority.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' backend/connect_local_jitsi.py
if ($LASTEXITCODE -ne 0) { throw 'Local setup failed.' }
$localCertPath = Join-Path $PSScriptRoot 'backend/data/jitsi/config/storage/web/keys/localhost.cer'
$localCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($localCertPath)
if (-not (Test-Path -LiteralPath "Cert:\CurrentUser\Root\$($localCert.Thumbprint)")) {
    Import-Certificate -FilePath $localCertPath -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
}
docker compose --project-directory backend/data/jitsi up -d
if ($LASTEXITCODE -ne 0) { throw 'Open Docker Desktop and run this setup again.' }
docker compose --project-directory backend/data/jitsi restart web
if ($LASTEXITCODE -ne 0) { throw 'Meeting HTTPS service did not restart.' }
Write-Host 'Setup complete. Restart the app, sign in, and choose Start meeting. Employees join from their dashboard.'
