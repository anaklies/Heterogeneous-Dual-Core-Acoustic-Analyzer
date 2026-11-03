# First combined resource audit of the newly connected kernels and vendor
# infrastructure. This abstract BD still has internal AXI boundary ports.
# Do not insert physical IO pads for them and do not generate a bitstream.
set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
set out $root/tmp/p17_board_kernels
set_param general.maxThreads 2
open_project $out/project/board_kernels.xpr
set bd [get_files $out/assets/vendor_bd/design_1.bd]
generate_target all $bd
set wrappers [make_wrapper -files $bd -top]
add_files -norecurse $wrappers
set_property top design_1_wrapper [current_fileset]
set_property -dict [list {STEPS.SYNTH_DESIGN.ARGS.MORE OPTIONS} {-mode out_of_context}] [get_runs synth_1]
launch_runs synth_1 -jobs 2
wait_on_run synth_1
set status [get_property STATUS [get_runs synth_1]]
if {![string match "*Complete*" $status]} {error "Combined synthesis failed: $status"}
open_run synth_1
report_utilization -file $out/combined_utilization.rpt
report_utilization -hierarchical -file $out/combined_hierarchy.rpt
report_timing_summary -file $out/combined_synth_timing.rpt
set fp [open $out/combined_blackboxes.txt w]
puts $fp [get_cells -hier -filter {IS_BLACKBOX == 1}]
close $fp
write_checkpoint -force $out/combined_kernels_synth.dcp
puts "COMBINED_KERNEL_SYNTHESIS_DONE_NOT_PHYSICAL_TOP"
close_project
