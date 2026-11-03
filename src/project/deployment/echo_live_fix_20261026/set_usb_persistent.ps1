$ErrorActionPreference='Stop'
$d=Split-Path -Parent $PSCommandPath
$a=@(Get-NetAdapter | Where-Object {$_.InterfaceDescription -eq 'Realtek USB GbE Family Controller' -and $_.MacAddress -eq '00-E0-4C-19-11-58'})
if($a.Count -ne 1){throw 'Dedicated USB adapter identity mismatch'}
if(!(Test-Path "$d/USB_NETWORK_PERSIST_BEFORE.xml")){Get-NetIPConfiguration -InterfaceIndex $a[0].ifIndex -Detailed | Export-Clixml "$d/USB_NETWORK_PERSIST_BEFORE.xml"}
& netsh interface ipv4 set address "name=$($a[0].Name)" source=static address=192.168.77.1 mask=255.255.255.0 gateway=none store=persistent | Out-Null
if($LASTEXITCODE -ne 0){throw 'netsh failed'}
[ordered]@{adapter=$a[0].Name;index=$a[0].ifIndex;ip='192.168.77.1';board='192.168.77.2';persistent=$true;defaultGatewayAdded=$false}|ConvertTo-Json|Set-Content "$d/NETWORK_PERSIST_RESULT.json" -Encoding UTF8