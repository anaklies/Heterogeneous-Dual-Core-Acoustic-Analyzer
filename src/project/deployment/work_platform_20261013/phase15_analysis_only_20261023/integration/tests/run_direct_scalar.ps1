$ErrorActionPreference='Stop'
$integration=Split-Path $PSScriptRoot -Parent
$root=(Resolve-Path "$integration/../../../..").Path
$impl="$root/tmp/p20_scalar/hls/impl"
$sim="$root/tmp/p21_scalar_rtl"
New-Item -ItemType Directory -Force $sim | Out-Null
Copy-Item 'D:/2025.2/Vivado/data/xsim/xsim.ini' "$sim/xsim.ini"
Get-ChildItem "$impl/verilog/*.dat" | Copy-Item -Destination $sim
$entries=@()
Get-ChildItem "$impl/ip/hdl/ip/*/*.xci" | ForEach-Object {
 $name=$_.BaseName
 $wrapper="$impl/ip/subcore_prj/subcore_prj.gen/sources_1/ip/$name/sim/$name.vhd"
 if(!(Test-Path $wrapper)){throw "Missing actual exported wrapper: $wrapper"}
 $entries+='vhdl xil_defaultlib "'+$wrapper.Replace('\','/')+'"'
}
Get-ChildItem "$impl/verilog/*.v" | ForEach-Object {$entries+='sv xil_defaultlib "'+$_.FullName.Replace('\','/')+'"'}
$entries+='sv xil_defaultlib "D:/2025.2/Vivado/data/verilog/src/glbl.v"'
$entries+='sv xil_defaultlib "'+"$integration/tests/tb_scalar_rtl.sv".Replace('\','/')+'"'
Set-Content "$sim/direct_scalar.prj" $entries
Push-Location $sim
try {
 & 'D:/2025.2/Vivado/bin/xelab.bat' xil_defaultlib.tb_scalar_rtl xil_defaultlib.glbl -prj direct_scalar.prj -i "$impl/verilog" -L xil_defaultlib -L unisims_ver -L xpm -L floating_point_v7_1_21 -L floating_point_v7_0_26 -relax -s direct_scalar_safe *> "$integration/results/direct_scalar_safe_elab.log"
 if($LASTEXITCODE){throw 'Actual scalar RTL elaboration failed'}
 & 'D:/2025.2/Vivado/bin/xsim.bat' direct_scalar_safe -runall *> "$integration/results/direct_scalar_safe_sim.log"
 $log=Get-Content "$integration/results/direct_scalar_safe_sim.log" -Raw
 if($LASTEXITCODE -or $log -match 'Fatal:' -or $log -notmatch 'ACTUAL_SCALAR_RTL_DONE'){throw 'Actual scalar RTL checks did not pass'}
 if($log -match 'cannot be opened for reading'){throw 'Missing simulation ROM initialization'}
 & "$root/deployment/work_platform_20261013/phase12h_srp_dnn_salsa_20261020/.venv/Scripts/python.exe" "$integration/tests/verify_scalar_rtl.py"
 if($LASTEXITCODE){throw 'Actual scalar RTL numerical verification failed'}
 Write-Output ($log -split "`n" | Where-Object {$_ -match 'ACTUAL_SCALAR_RTL_DONE|INVALID_COMPLEX_REJECTED'})
} finally {Pop-Location}
