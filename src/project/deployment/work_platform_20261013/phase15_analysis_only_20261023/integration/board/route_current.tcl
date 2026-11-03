set root C:/Users/sunxi/Desktop/sixmic3D
set out $root/tmp/p22_instrument_board_v4
if {[file exists $out/routed.dcp] && ![info exists ::env(SIXMIC_EXPLICIT_REBUILD)]} {error "Current routed evidence exists. Reuse it; set SIXMIC_EXPLICIT_REBUILD only after relevant source/constraint change."}
set here $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration
open_project $out/project/instrument_board.xpr
set_param general.maxThreads 2
if {[llength [get_files -quiet $here/board/cdc_timing.xdc]]==0} {add_files -fileset constrs_1 $here/board/cdc_timing.xdc}
set_property USED_IN_SYNTHESIS false [get_files $here/board/cdc_timing.xdc]
set_property PROCESSING_ORDER LATE [get_files $here/board/cdc_timing.xdc]
reset_run impl_1
launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]]!="100%"} {error "Implementation failed"}
open_run impl_1
report_utilization -file $here/results/board_routed_utilization.rpt
report_timing_summary -report_unconstrained -file $here/results/board_routed_timing.rpt
report_drc -file $here/results/board_routed_drc.rpt
report_cdc -file $here/results/board_routed_cdc.rpt
report_bus_skew -file $here/results/board_gray_skew.rpt
report_methodology -file $here/results/board_methodology.rpt
write_checkpoint -force $out/routed.dcp
puts CURRENT_BOARD_ROUTE_DONE
