param([string]$IPAddress)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $IPAddress) {
    $route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1
    $IPAddress = (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 | Where-Object {$_.PrefixOrigin -ne 'WellKnown'} | Select-Object -First 1).IPAddress
}
if (-not $IPAddress) { throw 'Connect Wi-Fi or a phone hotspot first, or pass -IPAddress with the laptop Wi-Fi address.' }
& '.\.venv\Scripts\python.exe' backend/setup_network.py --ip $IPAddress
if ($LASTEXITCODE -ne 0) { throw 'Wi-Fi setup failed.' }
$caPath = Join-Path $PSScriptRoot 'backend/data/network/public/meeting-brain-wifi.crt'
$ca = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($caPath)
if (-not (Test-Path -LiteralPath "Cert:\CurrentUser\Root\$($ca.Thumbprint)")) {
    Import-Certificate -FilePath $caPath -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
}
$firewallScript = Join-Path $PSScriptRoot 'backend/allow-network-meetings.ps1'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) { & $firewallScript -IPAddress $IPAddress }
else {
    # Windows needs its one-time UAC approval to create the narrowly scoped rules.
    $shellPath = (Get-Process -Id $PID).Path
    $firewallProcess = Start-Process -FilePath $shellPath -Verb RunAs -WindowStyle Hidden -Wait -PassThru `
        -ArgumentList @('-NoProfile','-File',('"' + $firewallScript + '"'),'-IPAddress',$IPAddress)
    if ($firewallProcess.ExitCode -ne 0) { throw 'Wi-Fi firewall setup was not completed.' }
}
docker compose --project-directory backend/data/jitsi up -d
if ($LASTEXITCODE -ne 0) { throw 'Open Docker Desktop and run setup again.' }
docker compose --project-directory backend/data/jitsi restart web
if ($LASTEXITCODE -ne 0) { throw 'Meeting HTTPS service did not restart.' }
Write-Host "Ready. Run ./start.ps1. Phone setup: http://${IPAddress}:8101  App: https://${IPAddress}:8100/login"
