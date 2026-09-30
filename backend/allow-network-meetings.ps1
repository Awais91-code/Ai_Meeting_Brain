param([Parameter(Mandatory=$true)][string]$IPAddress)
$ErrorActionPreference = 'Stop'
$address = [System.Net.IPAddress]::Parse($IPAddress)
if ($address.AddressFamily -ne 'InterNetwork') { throw 'An IPv4 address is required.' }
$adapter = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $IPAddress -ErrorAction Stop | Select-Object -First 1
if (-not $adapter) { throw 'The address must belong to this laptop.' }
$prefix = 'MeetingBrain-WiFi-'
foreach ($rule in @(@{Name='Web';Protocol='TCP';Ports=@('8100','8101','8443')},@{Name='Media';Protocol='UDP';Ports=@('10000')})) {
    $ruleName = $prefix + $rule.Name
    if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -Name $ruleName }
    New-NetFirewallRule -Name $ruleName -DisplayName ('Meeting Brain Wi-Fi ' + $rule.Name) -Group 'Meeting Brain Wi-Fi demo' `
        -Direction Inbound -Action Allow -Enabled True -Protocol $rule.Protocol -LocalPort $rule.Ports `
        -LocalAddress $IPAddress -RemoteAddress LocalSubnet -InterfaceAlias $adapter.InterfaceAlias -Profile Any | Out-Null
}
Write-Host 'Allowed only Meeting Brain web/media ports from the local subnet on the selected adapter.'
