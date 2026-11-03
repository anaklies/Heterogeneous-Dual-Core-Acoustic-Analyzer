# Private analysis-only candidate. Old BD, IP and boot files are read-only.
set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../..]
set prior $root/deployment/work_platform_20261013/phase14_room_and_pl_20261021/pl_system/board
set fp [open $prior/build_location.txt r];set baseline [string trim [read $fp]];close $fp
set out $root/tmp/p18_analysis_board
file mkdir $out/assets
set_param general.maxThreads 2
create_project analysis_board $out/project -part xc7z020clg484-2 -force
set repos [list $root/deployment/system_candidate_20261012/vendor_ip]
foreach build {p18_analysis_extended p18_shared_fft} {
    set repo $root/tmp/$build/hls/impl/ip
    if {![file exists $repo/component.xml]} {error "Missing real IP $repo"}
    lappend repos $repo
}
set_property ip_repo_paths $repos [current_project]
update_ip_catalog
if {![file exists $out/assets/vendor_bd/design_1.bd]} {file copy $baseline/assets/vendor_bd $out/assets/vendor_bd}
read_bd $out/assets/vendor_bd/design_1.bd
open_bd_design [get_files $out/assets/vendor_bd/design_1.bd]
set_property -dict [list CONFIG.NUM_OUT_CLKS {2} CONFIG.CLKOUT2_USED {true} CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {50.000}] [get_bd_cells clk_wiz_acoustic]
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 analysis_reset
set c50 [get_bd_pins clk_wiz_acoustic/clk_out2]
set c75 [get_bd_pins clk_wiz_acoustic/clk_out1]
set c100 [get_bd_pins processing_system7_0/FCLK_CLK0]
set r75 [get_bd_pins acoustic_reset/peripheral_aresetn]
set r100 [get_bd_pins proc_sys_reset_100m/peripheral_aresetn]
connect_bd_net $c50 [get_bd_pins analysis_reset/slowest_sync_clk]
connect_bd_net [get_bd_pins clk_wiz_acoustic/locked] [get_bd_pins analysis_reset/dcm_locked]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins analysis_reset/ext_reset_in]
set r50 [get_bd_pins analysis_reset/peripheral_aresetn]
create_bd_port -dir O -type clk analysis_clk_50
set_property -dict [list CONFIG.FREQ_HZ 50000000 CONFIG.ASSOCIATED_RESET analysis_resetn_50] [get_bd_ports analysis_clk_50]
connect_bd_net $c50 [get_bd_ports analysis_clk_50]
create_bd_port -dir O -type rst analysis_resetn_50
set_property CONFIG.POLARITY ACTIVE_LOW [get_bd_ports analysis_resetn_50]
connect_bd_net $r50 [get_bd_ports analysis_resetn_50]

foreach {name vlnv} {analysis xilinx.com:hls:analysis_dma_safe:1.0 fft xilinx.com:hls:analysis_fft2048:1.0} {
    create_bd_cell -type ip -vlnv $vlnv $name
    connect_bd_net $c50 [get_bd_pins $name/ap_clk]
    connect_bd_net $r50 [get_bd_pins $name/ap_rst_n]
}
# Include the real event state machine in this resource measurement. Its feature
# input and config boundary are internal integration ports, not physical pins.
add_files -norecurse $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/event/event_power_detector.sv
add_files -norecurse $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/event/event_power_detector_bd.v
update_compile_order -fileset sources_1
create_bd_cell -type module -reference event_power_detector_bd event_core
connect_bd_net $c50 [get_bd_pins event_core/clk]
connect_bd_net $r50 [get_bd_pins event_core/rst_n]
foreach pin [get_bd_pins -of_objects [get_bd_cells event_core]] {
    if {[file tail $pin] ni {clk rst_n}} {make_bd_pins_external $pin}
}
# Data and register fabrics are separate. No DDR port can address registers.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 analysis_data
set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 1] [get_bd_cells analysis_data]
connect_bd_net $c50 [get_bd_pins analysis_data/aclk]
connect_bd_net $r50 [get_bd_pins analysis_data/aresetn]
connect_bd_intf_net [get_bd_intf_pins analysis/m_axi_memory] [get_bd_intf_pins analysis_data/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins fft/m_axi_memory] [get_bd_intf_pins analysis_data/S01_AXI]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_clock_converter:2.1 data_crossing
set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.DATA_WIDTH 32 CONFIG.ADDR_WIDTH 32 CONFIG.ID_WIDTH 3 CONFIG.ACLK_ASYNC 1 CONFIG.SYNCHRONIZATION_STAGES 3] [get_bd_cells data_crossing]
connect_bd_net $c50 [get_bd_pins data_crossing/s_axi_aclk]
connect_bd_net $r50 [get_bd_pins data_crossing/s_axi_aresetn]
connect_bd_net $c75 [get_bd_pins data_crossing/m_axi_aclk]
connect_bd_net $r75 [get_bd_pins data_crossing/m_axi_aresetn]
connect_bd_intf_net [get_bd_intf_pins analysis_data/M00_AXI] [get_bd_intf_pins data_crossing/S_AXI]
delete_bd_objs [get_bd_intf_nets -of_objects [get_bd_intf_ports S_AXI_ACOUSTIC]]
set_property CONFIG.ID_WIDTH 4 [get_bd_cells acoustic_clock_crossing]
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 capture_data
set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 1] [get_bd_cells capture_data]
connect_bd_net $c75 [get_bd_pins capture_data/aclk]
connect_bd_net $r75 [get_bd_pins capture_data/aresetn]
connect_bd_intf_net [get_bd_intf_ports S_AXI_ACOUSTIC] [get_bd_intf_pins capture_data/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins data_crossing/M_AXI] [get_bd_intf_pins capture_data/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins capture_data/M00_AXI] [get_bd_intf_pins acoustic_clock_crossing/S_AXI]

set_property CONFIG.NUM_MI 7 [get_bd_cells axi_interconnect_0]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_clock_converter:2.1 ps_analysis_control
set_property -dict [list CONFIG.PROTOCOL AXI4LITE CONFIG.DATA_WIDTH 32 CONFIG.ADDR_WIDTH 32 CONFIG.ACLK_ASYNC 1 CONFIG.SYNCHRONIZATION_STAGES 3] [get_bd_cells ps_analysis_control]
connect_bd_net $c100 [get_bd_pins axi_interconnect_0/M06_ACLK] [get_bd_pins ps_analysis_control/s_axi_aclk]
connect_bd_net $r100 [get_bd_pins axi_interconnect_0/M06_ARESETN] [get_bd_pins ps_analysis_control/s_axi_aresetn]
connect_bd_net $c50 [get_bd_pins ps_analysis_control/m_axi_aclk]
connect_bd_net $r50 [get_bd_pins ps_analysis_control/m_axi_aresetn]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M06_AXI] [get_bd_intf_pins ps_analysis_control/S_AXI]
create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:aximm_rtl:1.0 S_AXI_JOB
set_property -dict [list CONFIG.PROTOCOL AXI4LITE CONFIG.ADDR_WIDTH 32 CONFIG.DATA_WIDTH 32 CONFIG.FREQ_HZ 50000000] [get_bd_intf_ports S_AXI_JOB]
set_property CONFIG.ASSOCIATED_BUSIF S_AXI_JOB [get_bd_ports analysis_clk_50]
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 analysis_control
set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 2 CONFIG.NUM_CLKS 1] [get_bd_cells analysis_control]
connect_bd_net $c50 [get_bd_pins analysis_control/aclk]
connect_bd_net $r50 [get_bd_pins analysis_control/aresetn]
connect_bd_intf_net [get_bd_intf_ports S_AXI_JOB] [get_bd_intf_pins analysis_control/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins ps_analysis_control/M_AXI] [get_bd_intf_pins analysis_control/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins analysis_control/M00_AXI] [get_bd_intf_pins analysis/s_axi_control]
connect_bd_intf_net [get_bd_intf_pins analysis_control/M01_AXI] [get_bd_intf_pins fft/s_axi_control]
set ddr [get_bd_addr_segs processing_system7_0/S_AXI_HP1/HP1_DDR_LOWOCM]
foreach name {analysis fft} {
    set space [get_bd_addr_spaces -of_objects [get_bd_intf_pins $name/m_axi_memory]]
    assign_bd_address -offset 0 -range 0x40000000 -target_address_space $space $ddr
}
foreach {name address} {analysis 0x44A30000 fft 0x44A40000} {
    foreach space [list [get_bd_addr_spaces S_AXI_JOB] [get_bd_addr_spaces processing_system7_0/Data]] {
        assign_bd_address -offset $address -range 64K -target_address_space $space [get_bd_addr_segs $name/s_axi_control/Reg]
    }
}
validate_bd_design
save_bd_design
write_bd_tcl -force $here/generated_analysis_bd.tcl
set fp [open $here/address_map.txt w]
foreach space [get_bd_addr_spaces] {
    puts $fp "SPACE $space"
    foreach segment [get_bd_addr_segs -of_objects $space] {puts $fp "  $segment [get_property OFFSET $segment] [get_property RANGE $segment]"}
}
close $fp
set bd [get_files $out/assets/vendor_bd/design_1.bd]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top design_1_wrapper [current_fileset]
set_property -dict [list {STEPS.SYNTH_DESIGN.ARGS.MORE OPTIONS} {-mode out_of_context}] [get_runs synth_1]
launch_runs synth_1 -jobs 2
wait_on_run synth_1
set state [get_property STATUS [get_runs synth_1]]
if {![string match "*Complete*" $state]} {error "Synthesis failed: $state"}
open_run synth_1
report_utilization -file $here/combined_utilization.rpt
report_utilization -hierarchical -file $here/combined_hierarchy.rpt
report_timing_summary -file $here/combined_synth_timing.rpt
set boxes [get_cells -hier -filter {IS_BLACKBOX == 1}]
set fp [open $here/blackboxes.txt w];puts $fp $boxes;close $fp
write_checkpoint -force $out/analysis_only_synth.dcp
puts "ANALYSIS_ONLY_SYNTHESIS_COMPLETE_NOT_PHYSICAL_TOP"
close_project
