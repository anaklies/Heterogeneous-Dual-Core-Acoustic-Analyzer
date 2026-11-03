set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
set project $root/tmp/p28_recovery_fix/instrument_board
set out $root/deployment/releases/SixMic3D_PL_Analysis_RC1_RecoveryFix_20261024
file mkdir $out/hardware
open_project $project/instrument_board.xpr
set rom [get_files -all *stream_fft2048_HANN2048_ROM_AUTO_1R.v]
if {[llength $rom]!=1} {error "Expected one original FFT ROM module"}
set dat [file normalize [file dirname [lindex $rom 0]]/stream_fft2048_HANN2048_ROM_AUTO_1R.dat]
if {![string match "[string tolower $project]/*" [string tolower $dat]]} {error "Data copy must remain inside private project"}
file copy -force $here/stream_fft2048_HANN2048_ROM_AUTO_1R.dat $dat
add_files $dat
archive_project -force $out/hardware/recoverable_project.zip
puts RC1_RECOVERY_DEPENDENCY_FIXED
