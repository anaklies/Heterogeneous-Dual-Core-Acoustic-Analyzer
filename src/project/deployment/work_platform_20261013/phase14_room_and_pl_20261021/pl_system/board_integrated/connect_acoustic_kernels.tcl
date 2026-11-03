# New private copy of the validated vendor PS7/HDMI design. No old build edits.
set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
set old $root/deployment/work_platform_20261013/phase14_room_and_pl_20261021/pl_system/board
set fp [open $old/build_location.txt r]
set old_build [string trim [read $fp]]
close $fp
set out $root/tmp/p17_board_kernels
file mkdir $out/assets
set_param general.maxThreads 2
create_project board_kernels $out/project -part xc7z020clg484-2 -force
set repos [list $root/deployment/system_candidate_20261012/vendor_ip]
foreach build {p16_frontend_split p16_nn_convshared p15_doa_shared p17_analysis_dma_safe} {
    set repo $root/tmp/$build/hls/impl/ip
    if {![file exists $repo/component.xml]} {error "Missing tested IP: $repo"}
    lappend repos $repo
}
set_property ip_repo_paths $repos [current_project]
update_ip_catalog
file copy $old_build/assets/vendor_bd $out/assets/vendor_bd
read_bd $out/assets/vendor_bd/design_1.bd
open_bd_design [get_files $out/assets/vendor_bd/design_1.bd]

#75MHz P0 and50MHz periodic/on-demand shared analysis, derived from the same
#100MHz PS FCLK. No change to the audio sampling clock.
set_property -dict [list CONFIG.NUM_OUT_CLKS {2} CONFIG.CLKOUT2_USED {true} \
    CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {50.000}] [get_bd_cells clk_wiz_acoustic]
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 analysis_reset
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out2] [get_bd_pins analysis_reset/slowest_sync_clk]
connect_bd_net [get_bd_pins clk_wiz_acoustic/locked] [get_bd_pins analysis_reset/dcm_locked]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins analysis_reset/ext_reset_in]
set clk75 [get_bd_pins clk_wiz_acoustic/clk_out1]
set reset75 [get_bd_pins acoustic_reset/peripheral_aresetn]
set clk50 [get_bd_pins clk_wiz_acoustic/clk_out2]
set reset50 [get_bd_pins analysis_reset/peripheral_aresetn]
set clk100 [get_bd_pins processing_system7_0/FCLK_CLK0]
set reset100 [get_bd_pins proc_sys_reset_100m/peripheral_aresetn]

foreach {name vlnv} {frontend xilinx.com:hls:acoustic_frontend_pipeline:1.0 nn xilinx.com:hls:nn_window:1.0 doa xilinx.com:hls:doa_first_shared:1.0 analysis xilinx.com:hls:analysis_dma_safe:1.0} {
    create_bd_cell -type ip -vlnv $vlnv $name
    if {$name eq "analysis"} {set c $clk50;set r $reset50} else {set c $clk75;set r $reset75}
    connect_bd_net $c [get_bd_pins $name/ap_clk]
    connect_bd_net $r [get_bd_pins $name/ap_rst_n]
}

# One shared address-decoded fabric. HLS master ports do real DDR access.
# RawPCM master and autonomous register bridge remain INTERNAL top interfaces.
set oldnet [get_bd_intf_nets -of_objects [get_bd_intf_ports S_AXI_ACOUSTIC]]
delete_bd_objs $oldnet
set_property CONFIG.ID_WIDTH 8 [get_bd_cells acoustic_clock_crossing]
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 kernel_fabric
set_property -dict [list CONFIG.NUM_SI {14} CONFIG.NUM_MI {5} CONFIG.NUM_CLKS {1}] [get_bd_cells kernel_fabric]
connect_bd_net $clk75 [get_bd_pins kernel_fabric/aclk]
connect_bd_net $reset75 [get_bd_pins kernel_fabric/aresetn]
connect_bd_intf_net [get_bd_intf_ports S_AXI_ACOUSTIC] [get_bd_intf_pins kernel_fabric/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins kernel_fabric/M00_AXI] [get_bd_intf_pins acoustic_clock_crossing/S_AXI]
create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:aximm_rtl:1.0 S_AXI_JOB
set_property -dict [list CONFIG.PROTOCOL {AXI4LITE} CONFIG.ADDR_WIDTH {32} CONFIG.DATA_WIDTH {32} CONFIG.FREQ_HZ {75000000}] [get_bd_intf_ports S_AXI_JOB]
connect_bd_intf_net [get_bd_intf_ports S_AXI_JOB] [get_bd_intf_pins kernel_fabric/S01_AXI]
set_property CONFIG.ASSOCIATED_BUSIF {S_AXI_ACOUSTIC:S_AXI_JOB} [get_bd_ports acoustic_clk_75]

set_property CONFIG.NUM_MI 7 [get_bd_cells axi_interconnect_0]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_clock_converter:2.1 ps_kernel_control
set_property -dict [list CONFIG.PROTOCOL {AXI4LITE} CONFIG.DATA_WIDTH {32} CONFIG.ADDR_WIDTH {32} CONFIG.ACLK_ASYNC {1} CONFIG.SYNCHRONIZATION_STAGES {3}] [get_bd_cells ps_kernel_control]
connect_bd_net $clk100 [get_bd_pins axi_interconnect_0/M06_ACLK] [get_bd_pins ps_kernel_control/s_axi_aclk]
connect_bd_net $reset100 [get_bd_pins axi_interconnect_0/M06_ARESETN] [get_bd_pins ps_kernel_control/s_axi_aresetn]
connect_bd_net $clk75 [get_bd_pins ps_kernel_control/m_axi_aclk]
connect_bd_net $reset75 [get_bd_pins ps_kernel_control/m_axi_aresetn]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M06_AXI] [get_bd_intf_pins ps_kernel_control/S_AXI]
connect_bd_intf_net [get_bd_intf_pins ps_kernel_control/M_AXI] [get_bd_intf_pins kernel_fabric/S02_AXI]

set si 3
foreach name {frontend nn doa} {
    foreach pin [lsort [get_bd_intf_pins -of_objects [get_bd_cells $name] -filter {MODE == Master}]] {
        connect_bd_intf_net $pin [get_bd_intf_pins [format "kernel_fabric/S%02d_AXI" $si]]
        incr si
    }
}
if {$si != 13} {error "Unexpected HLS master count, nextSI=$si"}

# Both channels of the slower shared analysis core have explicit CDC.
foreach {name protocol} {analysis_data_crossing AXI4 analysis_control_crossing AXI4LITE} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_clock_converter:2.1 $name
    set_property -dict [list CONFIG.PROTOCOL $protocol CONFIG.DATA_WIDTH {32} CONFIG.ADDR_WIDTH {32} CONFIG.ACLK_ASYNC {1} CONFIG.SYNCHRONIZATION_STAGES {3}] [get_bd_cells $name]
}
connect_bd_net $clk50 [get_bd_pins analysis_data_crossing/s_axi_aclk] [get_bd_pins analysis_control_crossing/m_axi_aclk]
connect_bd_net $reset50 [get_bd_pins analysis_data_crossing/s_axi_aresetn] [get_bd_pins analysis_control_crossing/m_axi_aresetn]
connect_bd_net $clk75 [get_bd_pins analysis_data_crossing/m_axi_aclk] [get_bd_pins analysis_control_crossing/s_axi_aclk]
connect_bd_net $reset75 [get_bd_pins analysis_data_crossing/m_axi_aresetn] [get_bd_pins analysis_control_crossing/s_axi_aresetn]
connect_bd_intf_net [get_bd_intf_pins analysis/m_axi_memory] [get_bd_intf_pins analysis_data_crossing/S_AXI]
connect_bd_intf_net [get_bd_intf_pins analysis_data_crossing/M_AXI] [get_bd_intf_pins kernel_fabric/S13_AXI]
connect_bd_intf_net [get_bd_intf_pins kernel_fabric/M04_AXI] [get_bd_intf_pins analysis_control_crossing/S_AXI]
connect_bd_intf_net [get_bd_intf_pins analysis_control_crossing/M_AXI] [get_bd_intf_pins analysis/s_axi_control]
foreach {index name} {1 frontend 2 nn 3 doa} {
    connect_bd_intf_net [get_bd_intf_pins [format "kernel_fabric/M%02d_AXI" $index]] [get_bd_intf_pins $name/s_axi_control]
}

set ddr [get_bd_addr_segs processing_system7_0/S_AXI_HP1/HP1_DDR_LOWOCM]
set jobspace [get_bd_addr_spaces S_AXI_JOB]
assign_bd_address -offset 0x00000000 -range 0x40000000 -target_address_space $jobspace $ddr
foreach name {frontend nn doa analysis} {
    foreach port [get_bd_intf_pins -of_objects [get_bd_cells $name] -filter {MODE == Master}] {
        set space [get_bd_addr_spaces -of_objects $port]
        assign_bd_address -offset 0x00000000 -range 0x40000000 -target_address_space $space $ddr
    }
}
foreach {name address} {frontend 0x44A00000 nn 0x44A10000 doa 0x44A20000 analysis 0x44A30000} {
    set segment [get_bd_addr_segs $name/s_axi_control/Reg]
    foreach space [list $jobspace [get_bd_addr_spaces processing_system7_0/Data]] {
        assign_bd_address -offset $address -range 64K -target_address_space $space $segment
    }
}
# Data masters can access DDR, not their own/other HLS control registers.
# PS uses its native DDR path; it must not use the GP0->HP1 loopback path.
set data_spaces [list [get_bd_addr_spaces S_AXI_ACOUSTIC]]
foreach name {frontend nn doa analysis} {
    foreach port [get_bd_intf_pins -of_objects [get_bd_cells $name] -filter {MODE == Master}] {
        lappend data_spaces [get_bd_addr_spaces -of_objects $port]
    }
}
foreach space $data_spaces {
    foreach name {frontend nn doa analysis} {
        exclude_bd_addr_seg -target_address_space $space [get_bd_addr_segs $name/s_axi_control/Reg]
    }
}
exclude_bd_addr_seg -target_address_space [get_bd_addr_spaces processing_system7_0/Data] $ddr
validate_bd_design
save_bd_design
set wrapper [make_wrapper -files [get_files $out/assets/vendor_bd/design_1.bd] -top]
add_files -norecurse $wrapper
set_property top design_1_wrapper [current_fileset]
set fp [open $here/build_location.txt w];puts $fp $out;close $fp
write_bd_tcl -force $here/generated_kernel_bd.tcl
set fp [open $here/address_map.txt w]
foreach space [get_bd_addr_spaces] {
    puts $fp "SPACE $space"
    foreach segment [get_bd_addr_segs -of_objects $space] {
        puts $fp "  $segment [get_property OFFSET $segment] [get_property RANGE $segment]"
    }
}
close $fp
puts "KERNEL_BOARD_BD_CONNECTED_AND_VALIDATED"
close_project
