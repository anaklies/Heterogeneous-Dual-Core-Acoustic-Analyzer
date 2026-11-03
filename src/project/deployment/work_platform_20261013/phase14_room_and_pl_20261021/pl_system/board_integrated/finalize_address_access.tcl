# Incremental access-policy fix only. Do not recreate or synthesize the BD.
set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
set out $root/tmp/p17_board_kernels
open_project $out/project/board_kernels.xpr
open_bd_design [get_files $out/assets/vendor_bd/design_1.bd]
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
exclude_bd_addr_seg -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs processing_system7_0/S_AXI_HP1/HP1_DDR_LOWOCM]
validate_bd_design
save_bd_design
write_bd_tcl -force $here/generated_kernel_bd.tcl
puts "KERNEL_BOARD_ACCESS_POLICY_VALIDATED"
close_project
