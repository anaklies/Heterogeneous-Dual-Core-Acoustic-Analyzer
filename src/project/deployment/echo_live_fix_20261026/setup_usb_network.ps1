$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSCommandPath
$adapter=Get-NetAdapter -InterfaceIndex 54
if($adapter.MacAddress -ne '00-E0-4C-19-11-58' -or $adapter.InterfaceDescription -ne 'Realtek USB GbE Family Controller'){throw 'USB adapter identity changed'}
Get-NetIPConfiguration -InterfaceIndex 54 -Detailed | Export-Clixml -LiteralPath (Join-Path $root 'USB_NETWORK_BEFORE.xml')
if(-not(Get-NetIPAddress -InterfaceIndex 54 -IPAddress 192.168.77.1 -ErrorAction SilentlyContinue)){
 Set-NetIPInterface -InterfaceIndex 54 -AddressFamily IPv4 -Dhcp Disabled -PolicyStore ActiveStore
 New-NetIPAddress -InterfaceIndex 54 -IPAddress 192.168.77.1 -PrefixLength 24 -PolicyStore ActiveStore | Out-Null
}
if(-not(Get-NetFirewallRule -DisplayName 'ECHO temporary patch transfer' -ErrorAction SilentlyContinue)){
 New-NetFirewallRule -DisplayName 'ECHO temporary patch transfer' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 48090 -LocalAddress 192.168.77.1 -RemoteAddress 192.168.77.2 -InterfaceAlias $adapter.Name -Profile Any | Out-Null
}
[ordered]@{status='PASS';interface=$adapter.Name;interfaceIndex=54;pcIP='192.168.77.1';boardIP='192.168.77.2';persistent=$false}|ConvertTo-Json|Set-Content (Join-Path $root 'NETWORK_SETUP.json') -Encoding UTF8
