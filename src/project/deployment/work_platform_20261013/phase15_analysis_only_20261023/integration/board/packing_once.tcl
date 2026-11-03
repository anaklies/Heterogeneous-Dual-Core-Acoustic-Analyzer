set root C:/Users/sunxi/Desktop/sixmic3D
set here $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration
set out $root/tmp/p23_control_packing
file mkdir $out
open_checkpoint $root/tmp/p22_instrument_board_v4/project/instrument_board.runs/impl_1/design_1_wrapper_opt.dcp
set_param general.maxThreads 2
set f [open $here/results/control_remap_candidates.txt r]
set names [split [read $f] "\n"];close $f
set chosen {}
foreach name $names {
 set nets [get_nets -quiet -segments $name]
 if {![llength $nets]} {continue}
 set ce [get_pins -leaf -quiet -of_objects $nets -filter {REF_PIN_NAME == CE}]
 set regs [get_cells -quiet -of_objects $ce -filter {REF_NAME == FDRE || REF_NAME == FDSE}]
 if {[llength $regs]>16} {continue}
 foreach reg $regs {
  if {[get_property ASYNC_REG $reg]==1 || [get_property DONT_TOUCH $reg]==1} {continue}
  if {![string match "*/instrument/*" $reg] || [string match "*/capture/*" $reg]} {continue}
  lappend chosen $reg
 }
}
set chosen [lsort -unique $chosen]
puts "TARGETED_CE_REMAP_REGISTERS [llength $chosen]"
if {[llength $chosen]<200} {error "Too little structural opportunity; retain verified route rather than spend another implementation"}
set_property CONTROL_SET_REMAP ENABLE $chosen
opt_design -property_opt_only
opt_design -control_set_merge -merge_equivalent_drivers
report_control_sets -file $out/control_sets_optimized.rpt
report_utilization -file $out/preplace_utilization.rpt
write_checkpoint -force $out/packing_opt.dcp
place_design
phys_opt_design -directive Explore
route_design
report_utilization -file $out/utilization.rpt
report_timing_summary -report_unconstrained -file $out/timing.rpt
report_drc -file $out/drc.rpt
report_cdc -file $out/cdc.rpt
report_bus_skew -file $out/bus_skew.rpt
write_checkpoint -force $out/routed.dcp
puts PACKING_CANDIDATE_COMPLETE
