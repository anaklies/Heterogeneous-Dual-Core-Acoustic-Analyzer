# One incremental clock-domain correction of the already validated NEW clone.
set here [file dirname [file normalize [info script]]]
set f [open $here/build_location.txt r]
set out [string trim [read $f]]
close $f
open_project $out/project/acoustic_board.xpr
set bd [get_files $out/assets/vendor_bd/design_1.bd]
open_bd_design $bd
foreach pin {acoustic_smartconnect/aclk acoustic_smartconnect/aclk1 acoustic_smartconnect/aresetn} {
    set p [get_bd_pins -quiet $pin]
    if {[llength $p]} {disconnect_bd_net [get_bd_nets -of_objects $p] $p}
}
set n [get_bd_intf_nets -of_objects [get_bd_intf_ports S_AXI_ACOUSTIC]]
delete_bd_objs $n
set_property CONFIG.NUM_CLKS 1 [get_bd_cells acoustic_smartconnect]
set_property CONFIG.ID_WIDTH 1 [get_bd_intf_ports S_AXI_ACOUSTIC]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_clock_converter:2.1 acoustic_clock_crossing
set_property -dict [list CONFIG.PROTOCOL {AXI4} CONFIG.ADDR_WIDTH {32} CONFIG.DATA_WIDTH {32} \
    CONFIG.ID_WIDTH {1} CONFIG.ACLK_ASYNC {1} CONFIG.SYNCHRONIZATION_STAGES {3}] [get_bd_cells acoustic_clock_crossing]
connect_bd_intf_net [get_bd_intf_ports S_AXI_ACOUSTIC] [get_bd_intf_pins acoustic_clock_crossing/S_AXI]
connect_bd_intf_net [get_bd_intf_pins acoustic_clock_crossing/M_AXI] [get_bd_intf_pins acoustic_smartconnect/S00_AXI]
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out1] [get_bd_pins acoustic_clock_crossing/s_axi_aclk]
connect_bd_net [get_bd_pins acoustic_reset/peripheral_aresetn] [get_bd_pins acoustic_clock_crossing/s_axi_aresetn]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins acoustic_smartconnect/aclk] [get_bd_pins acoustic_clock_crossing/m_axi_aclk]
connect_bd_net [get_bd_pins proc_sys_reset_100m/peripheral_aresetn] [get_bd_pins acoustic_smartconnect/aresetn] [get_bd_pins acoustic_clock_crossing/m_axi_aresetn]
validate_bd_design
if {[get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells acoustic_reset]] != 0} {error "Acoustic reset polarity is not active-low"}
save_bd_design
write_bd_tcl -force $here/generated_board_bd.tcl
set wrappers [make_wrapper -files $bd -top]
add_files -norecurse $wrappers
update_compile_order -fileset sources_1
set f [open $here/validated_properties.txt w]
foreach {name object property} {
    RESET_INPUT_ACTIVE_HIGH acoustic_reset CONFIG.C_EXT_RESET_HIGH
    CDC_ASYNC acoustic_clock_crossing CONFIG.ACLK_ASYNC
    CDC_STAGES acoustic_clock_crossing CONFIG.SYNCHRONIZATION_STAGES
    SMARTCONNECT_CLOCKS acoustic_smartconnect CONFIG.NUM_CLKS
    HP1_ENABLED processing_system7_0 CONFIG.PCW_USE_S_AXI_HP1
} {puts $f "$name [get_property $property [get_bd_cells $object]]"}
puts $f "CORE_CLOCK_HZ [get_property CONFIG.FREQ_HZ [get_bd_ports acoustic_clk_75]]"
puts $f "CORE_CLOCK_DOMAIN [get_property CONFIG.CLK_DOMAIN [get_bd_ports acoustic_clk_75]]"
puts $f "CORE_CLKOUT_ACTUAL [get_property CONFIG.CLKOUT1_REQUESTED_OUT_FREQ [get_bd_cells clk_wiz_acoustic]]"
close $f
puts ACOUSTIC_EXPLICIT_CDC_BD_VALIDATED_ONLY
close_project
exit
