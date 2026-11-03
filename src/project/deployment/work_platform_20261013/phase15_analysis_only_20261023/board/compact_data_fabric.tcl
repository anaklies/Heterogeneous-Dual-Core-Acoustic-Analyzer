# One measured major optimization: remove cascaded data fabrics/converters.
# Algorithm IP and event RTL remain bit-for-bit identical to the first build.
set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../..]
set out $root/tmp/p19_compact_data
file mkdir $out/assets
set_param general.maxThreads 2
create_project compact_data $out/project -part xc7z020clg484-2 -force
set_property ip_repo_paths [list $root/deployment/system_candidate_20261012/vendor_ip $root/tmp/p18_analysis_extended/hls/impl/ip $root/tmp/p18_shared_fft/hls/impl/ip] [current_project]
update_ip_catalog
add_files -norecurse [list $here/../event/event_power_detector.sv $here/../event/event_power_detector_bd.v]
if {![file exists $out/assets/vendor_bd/design_1.bd]} {file copy $root/tmp/p18_analysis_board/assets/vendor_bd $out/assets/vendor_bd}
read_bd $out/assets/vendor_bd/design_1.bd
open_bd_design [get_files $out/assets/vendor_bd/design_1.bd]
set old_cells [get_bd_cells {analysis_data capture_data data_crossing acoustic_clock_crossing acoustic_smartconnect}]
set nets {}
foreach c $old_cells {
    foreach pin [get_bd_intf_pins -of_objects $c] {
        foreach net [get_bd_intf_nets -of_objects $pin] {lappend nets $net}
    }
}
if {[llength $nets]} {delete_bd_objs [lsort -unique $nets]}
delete_bd_objs $old_cells
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ddr_data
set_property -dict [list CONFIG.NUM_SI 3 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 3] [get_bd_cells ddr_data]
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out2] [get_bd_pins ddr_data/aclk]
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out1] [get_bd_pins ddr_data/aclk1]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins ddr_data/aclk2]
connect_bd_net [get_bd_pins analysis_reset/peripheral_aresetn] [get_bd_pins ddr_data/aresetn]
connect_bd_intf_net [get_bd_intf_ports S_AXI_ACOUSTIC] [get_bd_intf_pins ddr_data/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins analysis/m_axi_memory] [get_bd_intf_pins ddr_data/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins fft/m_axi_memory] [get_bd_intf_pins ddr_data/S02_AXI]
connect_bd_intf_net [get_bd_intf_pins ddr_data/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP1]
validate_bd_design
save_bd_design
write_bd_tcl -force $here/generated_compact_bd.tcl
set bd [get_files $out/assets/vendor_bd/design_1.bd]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top design_1_wrapper [current_fileset]
set_property -dict [list {STEPS.SYNTH_DESIGN.ARGS.MORE OPTIONS} {-mode out_of_context}] [get_runs synth_1]
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {error "Compact synthesis failed"}
open_run synth_1
report_utilization -file $here/compact_utilization.rpt
report_utilization -hierarchical -file $here/compact_hierarchy.rpt
report_timing_summary -file $here/compact_synth_timing.rpt
set fp [open $here/compact_blackboxes.txt w];puts $fp [get_cells -hier -filter {IS_BLACKBOX == 1}];close $fp
write_checkpoint -force $out/compact_analysis_synth.dcp
puts "COMPACT_DATA_SYNTHESIS_COMPLETE_NOT_PHYSICAL_TOP"
close_project
