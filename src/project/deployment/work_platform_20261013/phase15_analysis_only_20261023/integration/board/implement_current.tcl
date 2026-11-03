set root C:/Users/sunxi/Desktop/sixmic3D
set out $root/tmp/p22_instrument_board_v4
if {[file exists $out/routed.dcp] && ![info exists ::env(SIXMIC_EXPLICIT_REBUILD)]} {error "Current routed evidence exists. Reuse it; set SIXMIC_EXPLICIT_REBUILD only after relevant source/constraint change."}
set reports $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/results
open_project $out/project/instrument_board.xpr
set_param general.maxThreads 2
update_compile_order -fileset sources_1
reset_run synth_1
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]]!="100%"} {error "Current full-board synthesis failed"}
open_run synth_1
report_utilization -hierarchical -file $reports/board_synth_hierarchy.rpt
report_utilization -file $reports/board_synth_utilization.rpt
report_timing_summary -report_unconstrained -file $reports/board_synth_timing.rpt
close_design
launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]]!="100%"} {error "Current full-board implementation failed"}
open_run impl_1
report_utilization -file $reports/board_routed_utilization.rpt
report_timing_summary -report_unconstrained -file $reports/board_routed_timing.rpt
report_drc -file $reports/board_routed_drc.rpt
report_cdc -file $reports/board_routed_cdc.rpt
write_checkpoint -force $out/routed.dcp
puts CURRENT_BOARD_ROUTE_DONE
