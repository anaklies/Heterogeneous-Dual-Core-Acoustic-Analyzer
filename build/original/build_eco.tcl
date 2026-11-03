# Bounded netlist change: independent microphone clock pads and isolated I2C pads.
# Original DSP/state machines, address map and PS initialization remain unchanged.
set root C:/Users/sunxi/Desktop/sixmic3D
set out $root/deployment/echo_separate_mic_clocks_20261026
file mkdir $out/hardware $out/reports
set_param general.maxThreads 2
open_checkpoint $root/deployment/releases/SixMic3D_PL_Analysis_RC1_RecoveryFix_20261024/hardware/routed.dcp
proc one {objects label} {
 if {[llength $objects]!=1} {error "$label expected one object, got $objects"}
 return [lindex $objects 0]
}
proc wire_to {net objects} {connect_net -hierarchical -net $net -objects $objects}
proc newnet {name objects} {
 set net [create_net $name]
 wire_to $net $objects
 return $net
}
set added_ports {}
foreach name {mic_sck mic_ws} pins {{U11 AB9 AB11 W8 W10} {U12 AB10 AA11 V8 W11}} {
 set old [one [get_cells ${name}_OBUF_inst] old_clock_buffer]
 set signal [one [get_nets -of_objects [get_pins $old/I]] clock_signal]
 create_port -direction OUT -from 4 -to 0 ${name}_copy
 for {set i 0} {$i<5} {incr i} {
  set port [get_ports [format {%s_copy[%d]} $name $i]]
  set cell [create_cell -reference OBUF echo_${name}_copy_$i]
  wire_to $signal [get_pins $cell/I]
  newnet echo_${name}_pad_$i [concat [get_pins $cell/O] $port]
  set_property PACKAGE_PIN [lindex $pins $i] $port
  set_property IOSTANDARD LVCMOS33 $port
  set_property SLEW SLOW $port
  lappend added_ports $port
 }
 puts "MIC_CLOCK_COPIES $name SAME_SOURCE $signal"
}
# The existing master latches the address at START. Only 0x44/0x45 (SHT)
# and 0x50 (IMU) can be issued by the frozen hub. Latched bit4 selects the bus.
set selector [one [get_cells -hier -regexp {.*bus/addr_reg\[4\]}] latched_sensor_selector]
set selectnet [one [get_nets -of_objects [get_pins $selector/Q]] selected_bus]
set new_luts {}
foreach suffix {scl sda} ball {AB6 AB7} {
 set oldport [get_ports sensor_$suffix]
 set pads [get_nets -segments -of_objects $oldport]
 set cells [get_cells -of_objects [get_pins -leaf -of_objects $pads]]
 set combined [filter $cells {REF_NAME == IOBUF}]
 if {[llength $combined]} {
  set buffer [one $combined existing_iobuf]
  set op [get_pins $buffer/O]
  set tp [get_pins $buffer/T]
  set ip [get_pins $buffer/I]
 } else {
  set ib [one [filter $cells {REF_NAME == IBUF}] existing_ibuf]
  set ob [one [filter $cells {REF_NAME == OBUFT}] existing_obuf]
  set op [get_pins $ib/O];set tp [get_pins $ob/T];set ip [get_pins $ob/I]
 }
 set feedback [one [get_nets -top_net_of_hierarchical_group -of_objects $op] sensor_feedback]
 set release [one [get_nets -top_net_of_hierarchical_group -of_objects $tp] original_open_drain_release]
 set low [one [get_nets -top_net_of_hierarchical_group -of_objects $ip] original_open_drain_zero]
 puts "SENSOR_SPLIT $suffix FEEDBACK $feedback RELEASE $release SELECT $selectnet"
 # Replace the macro at its external boundary. Its expanded primitive pins
 # cannot be edited directly. Core-side nets remain connected and preserved.
 if {[llength $combined]} {remove_cell $buffer} else {remove_cell [list $ib $ob]}
 set oldib [create_cell -reference IBUF echo_sht_${suffix}_IBUF]
 set oldob [create_cell -reference OBUFT echo_sht_${suffix}_OBUFT]
 set oldpad [one [get_nets -of_objects $oldport] old_sensor_pad]
 wire_to $oldpad [concat [get_pins $oldib/I] [get_pins $oldob/O]]
 wire_to $low [get_pins $oldob/I]
 create_port -direction INOUT imu_$suffix
 set port [get_ports imu_$suffix]
 set_property PACKAGE_PIN $ball $port
 set_property IOSTANDARD LVCMOS33 $port
 set_property PULLUP true $port
 set newib [create_cell -reference IBUF echo_imu_${suffix}_IBUF]
 set newob [create_cell -reference OBUFT echo_imu_${suffix}_OBUFT]
 newnet echo_imu_${suffix}_pad [concat [get_pins $newib/I] [get_pins $newob/O] $port]
 wire_to $low [get_pins $newob/I]
 set gate0 [create_cell -reference LUT2 echo_sht_${suffix}_release]
 set gate1 [create_cell -reference LUT2 echo_imu_${suffix}_release]
 set mux [create_cell -reference LUT3 echo_${suffix}_feedback]
 set_property INIT {4'hE} $gate0
 set_property INIT {4'hB} $gate1
 set_property INIT {8'hCA} $mux
 lappend new_luts $gate0 $gate1 $mux
 wire_to $release [concat [get_pins $gate0/I0] [get_pins $gate1/I0]]
 wire_to $selectnet [concat [get_pins $gate0/I1] [get_pins $gate1/I1] [get_pins $mux/I2]]
 newnet echo_sht_${suffix}_T [concat [get_pins $gate0/O] [get_pins $oldob/T]]
 newnet echo_imu_${suffix}_T [concat [get_pins $gate1/O] [get_pins $newob/T]]
 newnet echo_sht_${suffix}_in [concat [get_pins $oldib/O] [get_pins $mux/I0]]
 newnet echo_imu_${suffix}_in [concat [get_pins $newib/O] [get_pins $mux/I1]]
 wire_to $feedback [get_pins $mux/O]
 lappend added_ports $port
}
# Reuse all existing placements. Place six new tiny LUTs in unused slices.
foreach lut $new_luts {
 set target {}
 foreach site [get_sites -filter {SITE_TYPE == SLICEL}] {
  if {![llength [get_cells -quiet -of_objects $site]]} {set target $site;break}
 }
 if {$target eq {}} {error "No unused slice available for the bus selector"}
 place_cell $lut $target/A6LUT
}
place_ports $added_ports
route_design -preserve
report_route_status -file $out/reports/route_status.rpt
report_utilization -file $out/reports/utilization.rpt
report_timing_summary -report_unconstrained -file $out/reports/timing.rpt
report_drc -file $out/reports/drc.rpt
report_cdc -file $out/reports/cdc.rpt
report_io -file $out/reports/io.rpt
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {![llength $setup] || ![llength $hold]} {error "Missing timing evidence"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Timing failed; retain original bitstream"}
set errors [get_drc_violations -quiet -filter {SEVERITY == Error}]
if {[llength $errors]} {error "DRC errors: $errors"}
write_checkpoint -force $out/hardware/echo_separate_io.dcp
write_verilog -force $out/hardware/echo_separate_io_netlist.v
write_xdc -force $out/hardware/echo_separate_io.xdc
write_bitstream -force $out/hardware/echo_separate_io.bit
puts SEPARATE_IO_BITSTREAM_DONE
