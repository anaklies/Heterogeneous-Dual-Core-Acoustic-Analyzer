param([Parameter(Mandatory=$true)][string]$Command,[int]$TimeoutSec=30)
$port=New-Object System.IO.Ports.SerialPort('COM6',115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
try{$port.Open()}catch{[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'SERIAL_ERROR.txt'),$_.Exception.Message); Write-Output ('SERIAL_OPEN_ERROR '+$_.Exception.Message); exit 1}
Start-Sleep -Milliseconds 250
$tag='__C'+[guid]::NewGuid().ToString('N').Substring(0,6)
$port.DiscardInBuffer()
$port.Write(('echo '+$tag+'_BEGIN; '+$Command+'; echo '+$tag+'_END')+"`r")
$buf='';$lastData=[Diagnostics.Stopwatch]::StartNew();$sw=[Diagnostics.Stopwatch]::StartNew()
while($sw.Elapsed.TotalSeconds -lt $TimeoutSec){
  try{$t=$port.ReadExisting()}catch{$t=''}
  if($t.Length){$buf+=$t;$lastData.Restart()}
  if($sw.Elapsed.TotalSeconds -gt 2 -and ($buf -match 'root@[^\r\n]*#\s*$')){break}
  if($sw.Elapsed.TotalSeconds -gt 2 -and $lastData.Elapsed.TotalSeconds -gt 2.0){break}
  Start-Sleep -Milliseconds 100
}
$port.Close()
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'last_serial_output.txt'),$buf)
Write-Output $buf