set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
set out $root/tmp/p27_area_board
set project $out/instrument_board
set release $root/deployment/releases/SixMic3D_PL_Analysis_RC2_20261024
file mkdir $out/reports
file mkdir $release/hardware
open_project $project/instrument_board.xpr
set_param general.maxThreads 2
set old [get_files -all *fft_event_features.sv]
if {[llength $old]!=1} {error "Expected one feature source, got $old"}
remove_files $old
add_files $here/fft_event_features.sv
set rom $here/stream_fft2048_HANN2048_ROM_AUTO_1R.dat
if {![file exists $rom]} {error "Missing FFT window initialization"}
set old_data [get_files -quiet -all *stream_fft2048_HANN2048_ROM_AUTO_1R.dat]
if {[llength $old_data]>0} {remove_files $old_data}
set rom_hdl [get_files -all *stream_fft2048_HANN2048_ROM_AUTO_1R.v]
if {[llength $rom_hdl]!=1} {error "Expected one actual Hann ROM module"}
set local_rom [file normalize [file dirname [lindex $rom_hdl 0]]/stream_fft2048_HANN2048_ROM_AUTO_1R.dat]
if {![string match "[string tolower $project]/*" [string tolower $local_rom]]} {error "ROM copy must stay in private candidate project"}
file copy -force $rom $local_rom
add_files $local_rom
update_compile_order -fileset sources_1
# Reuse the archived synthesis reference when Vivado considers it applicable.
# No global strategy sweep or numeric-core rebuild is requested.
set_property AUTO_INCREMENTAL_CHECKPOINT 1 [get_runs synth_1]
reset_runs synth_1
set run_dir [get_property DIRECTORY [get_runs synth_1]]
file mkdir $run_dir
file copy -force $rom $run_dir/stream_fft2048_HANN2048_ROM_AUTO_1R.dat
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "RC2 synthesis failed"}
set f [open $run_dir/design_1_wrapper.vds r]
set synthlog [read $f]
close $f
if {[string first {CRITICAL WARNING:} $synthlog]>=0} {error "Review synthesis critical warning before implementation"}
launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "RC2 route failed"}
open_run impl_1
report_utilization -file $out/reports/utilization.rpt
report_utilization -hierarchical -file $out/reports/hierarchy.rpt
report_timing_summary -report_unconstrained -file $out/reports/timing.rpt
report_drc -file $out/reports/drc.rpt
report_cdc -file $out/reports/cdc.rpt
report_bus_skew -file $out/reports/bus_skew.rpt
report_methodology -file $out/reports/methodology.rpt
write_checkpoint -force $out/routed.dcp
set fh [open $out/reports/utilization.rpt r]
set utilization [read $fh]
close $fh
if {![regexp {[|] Slice LUTs[ *]+[|][ ]+([0-9]+)} $utilization -> luts]} {error "Missing LUT report"}
if {![regexp {[|] Slice[ ]+[|][ ]+([0-9]+)} $utilization -> slices]} {error "Missing Slice report"}
puts "RC2_AREA_RESULT LUT=$luts Slice=$slices"
if {$luts>39137 || $slices>13014} {error "Area gain insufficient; retain frozen RC1"}
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "Missing timing paths"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "RC2 timing gate failed"}
if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]>0} {error "RC2 DRC gate failed"}
close_design
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {error "Bitstream generation failed"}
set bit $project/instrument_board.runs/impl_1/design_1_wrapper.bit
if {![file exists $bit]} {error "No RC2 bitstream"}
file copy -force $bit $release/hardware/sixmic_analysis_rc2.bit
open_run impl_1
write_hw_platform -fixed -include_bit -force -file $release/hardware/sixmic_analysis_rc2.xsa
close_design
archive_project -force $release/hardware/recoverable_project.zip
puts RC2_BIT_XSA_ARCHIVE_DONE
