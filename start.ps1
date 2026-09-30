param([int]$Port = 8100, [switch]$LocalOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$projectPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Create .venv and install requirements.txt first. See README.md.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env'))) {
    throw 'Create the root .env from backend/.env.example first. See README.md.'
}

$env:PYTHONPATH = Join-Path $PSScriptRoot 'backend'
& $projectPython -m alembic -c backend/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed. Server was not started.' }

$networkConfig = Join-Path $PSScriptRoot 'backend/data/network/config.json'
$setupProcess = $null
$previousWorkerSetting = $env:WORKER_ENABLED

try {
    if (-not $LocalOnly) {
        if ($Port -ne 8100) {
            throw 'Wi-Fi/mobile mode uses port 8100. Use -LocalOnly for another local port.'
        }

        # Refresh the current Wi-Fi/hotspot address automatically. The same local
        # CA is reused, so a phone that already trusts it does not need to install
        # the certificate again after DHCP changes the laptop IP.
        & $projectPython backend/setup_network.py --auto
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not prepare the current Wi-Fi/mobile address. Connect the laptop to Wi-Fi or a phone hotspot and retry.'
        }
        if (-not (Test-Path -LiteralPath $networkConfig)) {
            throw 'Phone access configuration was not created.'
        }

        $network = Get-Content -LiteralPath $networkConfig -Raw | ConvertFrom-Json

        # Keep a single recovery worker if an older local-only server is open.
        try {
            $legacyApp = Invoke-RestMethod 'http://127.0.0.1:8000/' -TimeoutSec 2
            if ($legacyApp.message -eq 'AI Meeting Brain API is running') {
                $env:WORKER_ENABLED = 'false'
            }
        } catch { }

        $setupProcess = Start-Process -FilePath $projectPython -ArgumentList @('backend/device_setup_server.py') `
            -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru

        Write-Host ''
        Write-Host 'Meeting Brain is available on this laptop and phone:' -ForegroundColor Green
        Write-Host "  $($network.app_url)/login" -ForegroundColor Cyan
        Write-Host 'First-time Android certificate setup:' -ForegroundColor Green
        Write-Host "  $($network.setup_url)" -ForegroundColor Cyan
        Write-Host 'The address is auto-detected again on every start.' -ForegroundColor DarkGray
        Write-Host ''

        & $projectPython -m uvicorn app.main:app --app-dir backend --host $network.address --port $Port `
            --ssl-certfile $network.certificate_file --ssl-keyfile $network.key_file
    }
    else {
        & $projectPython -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $Port
    }
}
finally {
    $env:WORKER_ENABLED = $previousWorkerSetting
    if ($setupProcess -and -not $setupProcess.HasExited) {
        Stop-Process -Id $setupProcess.Id -ErrorAction SilentlyContinue
    }
}
