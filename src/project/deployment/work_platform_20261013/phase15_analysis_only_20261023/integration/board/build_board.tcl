# Private board project. Run only after review: Vivado 2025.2 -mode batch -source build_board.tcl
# No programming, erase, or mutation of p19/phase15 baseline assets.
set here [file dirname [file normalize [info script]]]
set integration [file dirname $here]
set root [file normalize $integration/../../../..]
set out $root/tmp/p22_instrument_board
if {[info exists ::env(SIXMIC_BOARD_OUTPUT)]} {set out [file normalize $::env(SIXMIC_BOARD_OUTPUT)]}
if {![string match "$root/tmp/*" $out]} {error "Board output must remain under workspace tmp"}
if {[file exists $out/project/instrument_board.xpr]} {error "Output exists: inspect/reuse it explicitly rather than overwrite"}
file mkdir $out
create_project instrument_board $out/project -part xc7z020clg484-2
set_param general.maxThreads 2
set_property ip_repo_paths [list $root/deployment/system_candidate_20261012/vendor_ip $root/tmp/p18_analysis_extended/hls/impl/ip $root/tmp/p18_shared_fft/hls/impl/ip] [current_project]
update_ip_catalog
# Use the same verified HLS netlist and dependent IP set as connected synthesis.
foreach build {p20_scalar p20_stream_fft} {
 set hdl $root/tmp/$build/hls/impl/ip/hdl
 add_files [glob $hdl/verilog/*.v]
 foreach inc [glob -nocomplain $hdl/verilog/*.vh] {add_files $inc;set_property file_type {Verilog Header} [get_files $inc]}
 foreach folder [glob -types d $hdl/ip/*] {
  foreach ipfile [glob -nocomplain $folder/*.xci] {read_ip $ipfile}
 }
}
set legacy $root/deployment/work_platform_20261013/phase14_room_and_pl_20261021/pl_system
add_files [list $legacy/hls_job_bridge.sv $legacy/axi_activity_guard.sv $root/deployment/work_platform_20261013/phase13_pl_port_20261021/rtl/control/pcm_axi_ring_writer.sv $root/pl/board/i2s_timing_gen.v $root/pl/board/i2s_rx_6ch.v]
foreach name {sample_cdc pcm_capture window_pool window_dma analysis_scheduler stream_job_bridge audio_pipeline analysis_runtime instrument_top} {add_files $integration/$name.sv}
add_files $root/deployment/work_platform_20261013/phase13_pl_port_20261021/rtl/control/mic_health.sv
add_files [list $integration/../event/event_power_detector.sv $integration/../event/event_power_detector_bd.v]
foreach name {runtime_control instrument_sensors event_recorder fft_event_features raw_cursor} {add_files $integration/control/$name.sv}
foreach name {sensor_i2c_hub i2c_transaction_master air_sound_speed} {add_files $root/deployment/environment_20261009/$name.sv}
add_files $here/instrument_bd.v
add_files $root/deployment/environment_20261009/air_coeff.mem
file copy -force $root/tmp/p19_compact_data/assets/vendor_bd $out/vendor_bd
add_files $out/vendor_bd/design_1.bd
open_bd_design $out/vendor_bd/design_1.bd
# Remove all old analysis-boundary interfaces and obsolete event scalar pins.
foreach name {M_AXI_MAILBOX S_AXI_ACOUSTIC S_AXI_JOB btns leds} {delete_bd_objs [get_bd_intf_ports -quiet $name]}
foreach name {mailbox_clk mailbox_resetn acoustic_clk_75 acoustic_resetn_75 acoustic_irq analysis_clk_50 analysis_resetn_50 background_bands_0 background_power_0 band_power_0 cfg_commit_0 cfg_data_0 channel_power_0 config_generation_0 feature_valid_0 in_ready_0 in_valid_0 learned_0 out_active_0 out_band_mask_0 out_config_generation_0 out_ended_0 out_ready_0 out_reason_0 out_started_0 out_timestamp_0 out_valid_0 sample_timestamp_0 sticky_fault_0} {delete_bd_objs [get_bd_ports -quiet $name]}
foreach name {analysis fft event_core analysis_control ddr_data acoustic_reset} {delete_bd_objs [get_bd_cells -quiet $name]}
# Keep video M00..M04; reuse former mailbox M05 for the host converter.
set obsolete [get_bd_intf_nets -of_objects [get_bd_intf_pins ps_analysis_control/S_AXI]]
delete_bd_objs $obsolete
set_property CONFIG.NUM_MI 6 [get_bd_cells axi_interconnect_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M05_AXI] [get_bd_intf_pins ps_analysis_control/S_AXI]
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 unused_buttons
set_property -dict [list CONFIG.CONST_WIDTH 2 CONFIG.CONST_VAL 0] [get_bd_cells unused_buttons]
connect_bd_net [get_bd_pins unused_buttons/dout] [get_bd_pins axi_gpio_btn/gpio_io_i]
create_bd_cell -type module -reference instrument_bd instrument
connect_bd_intf_net [get_bd_intf_pins ps_analysis_control/M_AXI] [get_bd_intf_pins instrument/HOST]
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 instrument_ddr
set_property -dict [list CONFIG.NUM_SI 5 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 2] [get_bd_cells instrument_ddr]
foreach {index bus} {0 RAW 1 WIN 2 FFT 3 SCALAR 4 FEATURE} {
 connect_bd_intf_net [get_bd_intf_pins instrument/$bus] [get_bd_intf_pins instrument_ddr/S0${index}_AXI]
}
connect_bd_intf_net [get_bd_intf_pins instrument_ddr/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP1]
connect_bd_net [get_bd_pins clk_wiz_acoustic/clk_out2] [get_bd_pins instrument/clk_compute] [get_bd_pins instrument_ddr/aclk]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins instrument_ddr/aclk1]
connect_bd_net [get_bd_pins analysis_reset/peripheral_aresetn] [get_bd_pins instrument/rst_n] [get_bd_pins instrument_ddr/aresetn]
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 audio_clock
set_property -dict [list CONFIG.PRIM_IN_FREQ 100.000 CONFIG.PRIM_SOURCE No_buffer CONFIG.RESET_TYPE ACTIVE_LOW CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 49.162011] [get_bd_cells audio_clock]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins audio_clock/clk_in1]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins audio_clock/resetn]
connect_bd_net [get_bd_pins audio_clock/clk_out1] [get_bd_pins instrument/clk_audio]
# Async assertion / synchronous deassertion is inside pcm_capture's audio domain.
# A missing clock lock is not acknowledged as successful recovery.
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 recovery_disabled
set_property CONFIG.CONST_VAL 0 [get_bd_cells recovery_disabled]
connect_bd_net [get_bd_pins recovery_disabled/dout] [get_bd_pins instrument/common_bus_reset_ack]
# Video IRQ slots0/1 stay untouched; old acoustic IRQ slot2 is reused.
connect_bd_net [get_bd_pins instrument/irq] [get_bd_pins xlconcat_0/In2]
foreach name {mic_sd mic_sck mic_ws sensor_scl sensor_sda} {make_bd_pins_external [get_bd_pins instrument/$name]; set_property name $name [get_bd_ports ${name}_0]}
# Do not export clocks, DDR AXI, job control, intermediate features, or reset pins.
puts "INSTRUMENT_ADDRESS_SEGMENTS [get_bd_addr_segs -hierarchical *instrument*]"
set host_segment [get_bd_addr_segs -of_objects [get_bd_intf_pins instrument/HOST]]
if {[llength $host_segment]!=1} {error "Expected one actual HOST segment, got: $host_segment"}
assign_bd_address -offset 0x43C20000 -range 0x1000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] $host_segment -force
foreach bus {RAW WIN FFT SCALAR FEATURE} {
 assign_bd_address -offset 0x00000000 -range 1G -target_address_space [get_bd_addr_spaces instrument/$bus] [get_bd_addr_segs processing_system7_0/S_AXI_HP1/HP1_DDR_LOWOCM] -force
}
save_bd_design
validate_bd_design
save_bd_design
write_bd_tcl -force $out/generated_instrument_bd.tcl
report_property [get_bd_cells audio_clock] -file $out/audio_clock_properties.txt
set bd [get_files $out/vendor_bd/design_1.bd]
generate_target all $bd
make_wrapper -files $bd -top -import
set_property top design_1_wrapper [current_fileset]
add_files -fileset constrs_1 $here/physical_pins.xdc
add_files -fileset constrs_1 $here/cdc_timing.xdc
set_property USED_IN_SYNTHESIS false [get_files $here/cdc_timing.xdc]
set_property PROCESSING_ORDER LATE [get_files $here/cdc_timing.xdc]
update_compile_order -fileset sources_1
# Default build stops at validated BD generation; parent can explicitly request implementation.
if {[info exists ::env(SIXMIC_FULL_BOARD_BUILD)] && $::env(SIXMIC_FULL_BOARD_BUILD)=="1"} {
 launch_runs synth_1 -jobs 2
 wait_on_run synth_1
 if {[get_property PROGRESS [get_runs synth_1]]!="100%"} {error "Synthesis failed"}
 launch_runs impl_1 -to_step route_design -jobs 2
 wait_on_run impl_1
 open_run impl_1
 report_utilization -file $out/full_utilization.rpt
 report_timing_summary -report_unconstrained -file $out/full_timing.rpt
 report_drc -file $out/full_drc.rpt
 report_cdc -file $out/full_cdc.rpt
 write_checkpoint -force $out/routed.dcp
 # Bitstream/export are separate release gates; do not suppress DRC to force them.
}
puts BOARD_DRAFT_GENERATED
