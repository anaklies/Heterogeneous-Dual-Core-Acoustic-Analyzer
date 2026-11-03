# New isolated PS7/HDMI plus acoustic DDR interface. No algorithm placeholder.
# Existing vendor BD, IP, bitstreams and startup files are read-only inputs.
set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
set vendor $root/deployment/system_candidate_20261012
set out $here/cache/board_[clock seconds]
file mkdir $out
set_param general.maxThreads 2
create_project acoustic_board $out/project -part xc7z020clg484-2
set_property ip_repo_paths [list $vendor/vendor_ip] [current_project]
update_ip_catalog

# Relative vendor XCI references stay inside this private copy when Vivado
# refreshes/generates the design. Do not read the old BD directly and save it.
set bdroot $out/assets/vendor_bd
file mkdir $bdroot
file copy $vendor/vendor_bd/design_1.bd $bdroot/design_1.bd
file copy $vendor/vendor_bd/ip $bdroot/ip
if {[file exists $vendor/vendor_bd/ipshared]} {file copy $vendor/vendor_bd/ipshared $bdroot/ipshared}
read_bd $bdroot/design_1.bd
set bd [get_files $bdroot/design_1.bd]
open_bd_design $bd
set ps [get_bd_cells processing_system7_0]
set_property -dict [list CONFIG.PCW_USE_S_AXI_HP1 {1}] $ps

# The PS I/O PLL's FCLK divider does not necessarily produce an exact75MHz
# when75 is requested. Derive exact75 from the existing100MHz FCLK0 instead.
# Existing display FCLK1 and HP0 connectivity are deliberately unchanged.
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clk_wiz_acoustic
set_property -dict [list CONFIG.PRIM_IN_FREQ {100.000} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {75.000} \
    CONFIG.PRIM_SOURCE {No_buffer} CONFIG.RESET_TYPE {ACTIVE_LOW}] [get_bd_cells clk_wiz_acoustic]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins clk_wiz_acoustic/clk_in1]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins clk_wiz_acoustic/resetn]
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 acoustic_reset
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out1] [get_bd_pins acoustic_reset/slowest_sync_clk]
connect_bd_net [get_bd_pins clk_wiz_acoustic/locked] [get_bd_pins acoustic_reset/dcm_locked]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins acoustic_reset/ext_reset_in]

create_bd_port -dir O -type clk acoustic_clk_75
set_property CONFIG.FREQ_HZ 75000000 [get_bd_ports acoustic_clk_75]
create_bd_port -dir O -type rst acoustic_resetn_75
set_property CONFIG.POLARITY ACTIVE_LOW [get_bd_ports acoustic_resetn_75]
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out1] [get_bd_ports acoustic_clk_75]
connect_bd_net [get_bd_pins acoustic_reset/peripheral_aresetn] [get_bd_ports acoustic_resetn_75]

# A slave interface on the BD boundary receives transactions from a PL AXI
# master. An explicit converter owns75-to100MHz CDC. SmartConnect owns
# the32-to64bit andAXI4-toAXI3 adaptation required by HP1.
create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:aximm_rtl:1.0 S_AXI_ACOUSTIC
set_property -dict [list CONFIG.PROTOCOL {AXI4} CONFIG.ADDR_WIDTH {32} \
    CONFIG.DATA_WIDTH {32} CONFIG.ID_WIDTH {1} CONFIG.FREQ_HZ {75000000} \
    CONFIG.HAS_BURST {1} CONFIG.MAX_BURST_LENGTH {16} \
    CONFIG.NUM_READ_OUTSTANDING {2} CONFIG.NUM_WRITE_OUTSTANDING {2} \
    CONFIG.SUPPORTS_NARROW_BURST {0}] [get_bd_intf_ports S_AXI_ACOUSTIC]
set_property -dict [list CONFIG.ASSOCIATED_BUSIF {S_AXI_ACOUSTIC} \
    CONFIG.ASSOCIATED_RESET {acoustic_resetn_75}] [get_bd_ports acoustic_clk_75]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_clock_converter:2.1 acoustic_clock_crossing
set_property -dict [list CONFIG.PROTOCOL {AXI4} CONFIG.ADDR_WIDTH {32} CONFIG.DATA_WIDTH {32} \
    CONFIG.ID_WIDTH {1} CONFIG.ACLK_ASYNC {1} CONFIG.SYNCHRONIZATION_STAGES {3}] [get_bd_cells acoustic_clock_crossing]
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 acoustic_smartconnect
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1} CONFIG.NUM_CLKS {1}] [get_bd_cells acoustic_smartconnect]
connect_bd_intf_net [get_bd_intf_ports S_AXI_ACOUSTIC] [get_bd_intf_pins acoustic_clock_crossing/S_AXI]
connect_bd_intf_net [get_bd_intf_pins acoustic_clock_crossing/M_AXI] [get_bd_intf_pins acoustic_smartconnect/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins acoustic_smartconnect/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP1]
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out1] [get_bd_pins acoustic_clock_crossing/s_axi_aclk]
connect_bd_net [get_bd_pins acoustic_reset/peripheral_aresetn] [get_bd_pins acoustic_clock_crossing/s_axi_aresetn]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins acoustic_smartconnect/aclk] \
    [get_bd_pins acoustic_clock_crossing/m_axi_aclk] [get_bd_pins processing_system7_0/S_AXI_HP1_ACLK]
connect_bd_net [get_bd_pins proc_sys_reset_100m/peripheral_aresetn] [get_bd_pins acoustic_smartconnect/aresetn] \
    [get_bd_pins acoustic_clock_crossing/m_axi_aresetn]
assign_bd_address -offset 0x00000000 -range 0x40000000 \
    -target_address_space [get_bd_addr_spaces S_AXI_ACOUSTIC] \
    [get_bd_addr_segs processing_system7_0/S_AXI_HP1/HP1_DDR_LOWOCM]

# Preserve old100MHz GP0 M_AXI_MAILBOX address aperture43C20000 and clock.
# The actual analysis register block is connected by the physical top later,
# using the verified guarded bridge when it runs in the75MHz domain.
set mailbox_segments [get_bd_addr_segs -of_objects [get_bd_addr_spaces processing_system7_0/Data] -filter {NAME =~ *M_AXI_MAILBOX*}]
if {[llength $mailbox_segments] != 1} {error "Expected one original mailbox address segment"}
set_property offset 0x43C20000 $mailbox_segments
set_property range 64K $mailbox_segments

set_property CONFIG.NUM_PORTS 3 [get_bd_cells xlconcat_0]
create_bd_port -dir I acoustic_irq
connect_bd_net [get_bd_ports acoustic_irq] [get_bd_pins xlconcat_0/In2]

validate_bd_design
if {[get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells acoustic_reset]] != 0} {error "Acoustic reset did not inherit active-low source polarity"}
save_bd_design
write_bd_tcl -force $here/generated_board_bd.tcl
set wrappers [make_wrapper -files $bd -top]
add_files -norecurse $wrappers
set_property top design_1_wrapper [current_fileset]
update_compile_order -fileset sources_1
set f [open $here/build_location.txt w]
puts $f $out
close $f
set f [open $here/validated_ports.txt w]
foreach p [get_bd_ports] {puts $f "PORT [get_property NAME $p] [get_property DIR $p]"}
foreach p [get_bd_intf_ports] {puts $f "INTERFACE [get_property NAME $p] [get_property MODE $p] [get_property VLNV $p]"}
puts $f "MAILBOX_OFFSET [get_property OFFSET $mailbox_segments]"
puts $f "MAILBOX_RANGE [get_property RANGE $mailbox_segments]"
puts $f "STATUS BD_VALIDATED_ONLY_NO_ALGORITHM_OR_BITSTREAM_ACCEPTANCE"
close $f
puts "ACOUSTIC_BOARD_BD_VALIDATED_ONLY $out"
close_project
exit
