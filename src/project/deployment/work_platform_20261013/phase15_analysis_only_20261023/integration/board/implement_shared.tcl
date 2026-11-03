set root C:/Users/sunxi/Desktop/sixmic3D
set out $root/tmp/p24_shared_instrument_board
set here $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration
set reports $out/reports
file mkdir $reports
open_project $out/project/instrument_board.xpr
set_param general.maxThreads 2
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]]!="100%"} {error "Shared fabric synthesis failed"}
open_run synth_1
report_utilization -hierarchical -file $reports/synth_hierarchy.rpt
report_utilization -file $reports/synth_utilization.rpt
report_timing_summary -report_unconstrained -file $reports/synth_timing.rpt
close_design
launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]]!="100%"} {error "Shared fabric implementation failed"}
open_run impl_1
report_utilization -file $reports/utilization.rpt
report_timing_summary -report_unconstrained -file $reports/timing.rpt
report_drc -file $reports/drc.rpt
report_cdc -file $reports/cdc.rpt
report_bus_skew -file $reports/bus_skew.rpt
report_methodology -file $reports/methodology.rpt
write_checkpoint -force $out/routed.dcp
puts FINAL_SHARED_BOARD_ROUTE_DONE
