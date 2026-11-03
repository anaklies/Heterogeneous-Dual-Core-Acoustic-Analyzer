# Rebuild an isolated copy. Original RC1 and the previous board bundle are kept.
set root [file normalize [file join [file dirname [info script]] ../src/project]]
set out [file normalize [lindex $argv 1]]
set project [file normalize [lindex $argv 0]]
file mkdir $out/reports $out/hardware
set_param general.maxThreads 2
open_project $project/instrument_board.xpr
foreach name {instrument_top.sv instrument_bd.v sensor_i2c_hub.sv i2c_transaction_master.sv} {
 foreach file [get_files -all *$name] {
  if {![string match "$project/*" [file normalize $file]]} {error "Source escaped private project: $file"}
 }
}
update_compile_order -fileset sources_1
set bd [get_files -all *design_1.bd]
if {[llength $bd]!=1} {error "Ambiguous block design: $bd"}
open_bd_design $bd
set mref [get_ips -all design_1_instrument_0]
puts "MODULE_REFERENCE_IP $mref"
update_module_reference $mref
foreach name {mic_sck_copy mic_ws_copy imu_scl imu_sda} {
 if {[llength [get_bd_pins -quiet instrument/$name]]!=1} {error "Missing new interface $name"}
 if {![llength [get_bd_ports -quiet $name]]} {
  make_bd_pins_external [get_bd_pins instrument/$name]
  set_property name $name [get_bd_ports ${name}_0]
 }
}
validate_bd_design
save_bd_design
generate_target all $bd
make_wrapper -files $bd -top -import
update_compile_order -fileset sources_1
reset_run synth_1
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis did not complete"}
set_property INCREMENTAL_CHECKPOINT {} [get_runs impl_1]
launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation did not complete"}
open_run impl_1
report_utilization -file $out/reports/utilization.rpt
report_timing_summary -report_unconstrained -file $out/reports/timing.rpt
report_drc -file $out/reports/drc.rpt
report_cdc -file $out/reports/cdc.rpt
report_route_status -file $out/reports/route_status.rpt
report_io -file $out/reports/io.rpt
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {![llength $setup] || ![llength $hold]} {error "Missing timing evidence"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Timing gate failed; no release"}
if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]} {error "DRC gate failed; no release"}
write_checkpoint -force $out/hardware/echo_separate_io.dcp
close_design
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Bitstream failed"}
file copy -force $project/instrument_board.runs/impl_1/design_1_wrapper.bit $out/hardware/echo_separate_io.bit
open_run impl_1
write_hw_platform -fixed -include_bit -force -file $out/hardware/echo_separate_io.xsa
close_design
archive_project -force $out/hardware/recoverable_project.zip
puts SEPARATE_IO_RELEASE_READY
