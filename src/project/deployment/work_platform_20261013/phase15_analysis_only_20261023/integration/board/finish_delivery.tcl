set root C:/Users/sunxi/Desktop/sixmic3D
set out $root/tmp/p24_shared_instrument_board
set release $root/deployment/releases/SixMic3D_PL_Analysis_RC1_20261024
file mkdir $out/reports
file mkdir $release/hardware
open_project $out/project/instrument_board.xpr
set_param general.maxThreads 2
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {
    error "Preserved synthesis must be complete; do not silently rebuild"
}
launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Route failed"}
open_run impl_1
report_utilization -file $out/reports/utilization.rpt
report_utilization -hierarchical -file $out/reports/hierarchy.rpt
report_timing_summary -report_unconstrained -file $out/reports/timing.rpt
report_drc -file $out/reports/drc.rpt
report_cdc -file $out/reports/cdc.rpt
report_bus_skew -file $out/reports/bus_skew.rpt
report_methodology -file $out/reports/methodology.rpt
write_checkpoint -force $out/routed.dcp
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "Missing timing evidence"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Timing gate failed"}
set errors [get_drc_violations -quiet -filter {SEVERITY == Error}]
if {[llength $errors]>0} {error "DRC errors block bitstream"}
close_design
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
set bit $out/project/instrument_board.runs/impl_1/design_1_wrapper.bit
if {![file exists $bit]} {error "No generated bitstream"}
file copy -force $bit $release/hardware/sixmic_analysis_rc1.bit
open_run impl_1
write_hw_platform -fixed -include_bit -force -file $release/hardware/sixmic_analysis_rc1.xsa
close_design
archive_project -force $release/hardware/recoverable_project.zip
puts DELIVERY_BIT_XSA_ARCHIVE_DONE
