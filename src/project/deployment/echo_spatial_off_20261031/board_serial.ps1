param(
  [Parameter(Mandatory=$true)][string]$Command,
  [int]$TimeoutSec = 90,
  [int]$SilenceSec = 20,
  [string]$OutFile = 'last_serial_output.txt'
)
# Derived from deployment/echo_stipa_8s_progress_20261030/board_serial.ps1.
# Difference: waits for the random __TAG_END line (not just an idle gap), so long
# commands such as sha256sum over the 166 MB image.ub are captured completely.
$port = New-Object System.IO.Ports.SerialPort('COM6',115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
try { $port.Open() } catch {
  [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'SERIAL_ERROR.txt'), $_.Exception.Message)
  Write-Output ('SERIAL_OPEN_ERROR ' + $_.Exception.Message)
  exit 1
}
Start-Sleep -Milliseconds 250
$tag = '__C' + [guid]::NewGuid().ToString('N').Substring(0,6)
$port.DiscardInBuffer()
$port.Write(('echo ' + $tag + '_BEGIN; ' + $Command + '; echo ' + $tag + '_END') + [char]13)
$buf = ''
$lastData = [Diagnostics.Stopwatch]::StartNew()
$sw = [Diagnostics.Stopwatch]::StartNew()
$endPattern = '(?m)^' + [regex]::Escape($tag) + '_END'
while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
  try { $t = $port.ReadExisting() } catch { $t = '' }
  if ($t.Length) { $buf += $t; $lastData.Restart() }
  if ($buf -match $endPattern) { break }
  if ($sw.Elapsed.TotalSeconds -gt 2 -and $lastData.Elapsed.TotalSeconds -gt $SilenceSec) { break }
  Start-Sleep -Milliseconds 100
}
Start-Sleep -Milliseconds 300
try { $buf += $port.ReadExisting() } catch { }
$port.Close()
[IO.File]::WriteAllText((Join-Path $PSScriptRoot $OutFile), $buf)
Write-Output $buf
