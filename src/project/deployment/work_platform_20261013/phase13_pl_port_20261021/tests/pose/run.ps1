$ErrorActionPreference='Stop'
$here=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
& 'D:/2025.2/Vivado/bin/xvlog.bat' --sv -i . ../../rtl/pose/s7_imu_rotation_q16.sv ../../rtl/pose/direction_pose_transform.sv tb_pose.sv *> compile.log
if($LASTEXITCODE -ne 0){throw 'pose compile failed'}
& 'D:/2025.2/Vivado/bin/xelab.bat' tb_pose -s pose_check *> elaborate.log
if($LASTEXITCODE -ne 0){throw 'pose elaborate failed'}
& 'D:/2025.2/Vivado/bin/xsim.bat' pose_check -runall -log simulate.log *> run.log
$content=Get-Content simulate.log -Raw
if($LASTEXITCODE -ne 0 -or !$content.Contains('POSE_TRANSFORM_PASS32') -or $content.Contains('Fatal:')){throw 'pose numerical test failed'}
Write-Output 'POSE_TRANSFORM_PASS32'
