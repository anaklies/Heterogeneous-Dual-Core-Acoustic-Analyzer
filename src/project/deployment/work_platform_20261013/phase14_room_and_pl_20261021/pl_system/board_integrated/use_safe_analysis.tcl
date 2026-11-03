set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
set out $root/tmp/p17_board_kernels
open_project $out/project/board_kernels.xpr
set repos [get_property ip_repo_paths [current_project]]
lappend repos $root/tmp/p17_analysis_dma_safe/hls/impl/ip
set_property ip_repo_paths $repos [current_project]
update_ip_catalog
open_bd_design [get_files $out/assets/vendor_bd/design_1.bd]
foreach pin [get_bd_intf_pins -of_objects [get_bd_cells analysis]] {
    disconnect_bd_intf_net [get_bd_intf_nets -of_objects $pin] $pin
}
delete_bd_objs [get_bd_cells analysis]
create_bd_cell -type ip -vlnv xilinx.com:hls:analysis_dma_safe:1.0 analysis
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out2] [get_bd_pins analysis/ap_clk]
connect_bd_net [get_bd_pins analysis_reset/peripheral_aresetn] [get_bd_pins analysis/ap_rst_n]
connect_bd_intf_net [get_bd_intf_pins analysis/m_axi_memory] [get_bd_intf_pins analysis_data_crossing/S_AXI]
connect_bd_intf_net [get_bd_intf_pins analysis/s_axi_control] [get_bd_intf_pins analysis_control_crossing/M_AXI]
set ddr [get_bd_addr_segs processing_system7_0/S_AXI_HP1/HP1_DDR_LOWOCM]
assign_bd_address -offset 0 -range 0x40000000 -target_address_space [get_bd_addr_spaces analysis/Data_m_axi_memory] $ddr
foreach space [list [get_bd_addr_spaces S_AXI_JOB] [get_bd_addr_spaces processing_system7_0/Data]] {
    assign_bd_address -offset 0x44A30000 -range 64K -target_address_space $space [get_bd_addr_segs analysis/s_axi_control/Reg]
}
set spaces [list [get_bd_addr_spaces S_AXI_ACOUSTIC]]
foreach name {frontend nn doa analysis} {
    foreach port [get_bd_intf_pins -of_objects [get_bd_cells $name] -filter {MODE == Master}] {
        lappend spaces [get_bd_addr_spaces -of_objects $port]
    }
}
foreach space $spaces {
    foreach name {frontend nn doa analysis} {
        exclude_bd_addr_seg -target_address_space $space [get_bd_addr_segs $name/s_axi_control/Reg]
    }
}
validate_bd_design
save_bd_design
write_bd_tcl -force $here/generated_kernel_bd.tcl
puts "SAFE_ANALYSIS_KERNEL_CONNECTED_VALIDATED"
close_project
