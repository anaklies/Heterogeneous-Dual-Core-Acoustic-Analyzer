set here [file dirname [file normalize [info script]]]
cd $here
create_project -in_memory -part xc7z020clg484-2
read_verilog -sv [file normalize ../../rtl/compute/shared_dot12.sv]
synth_design -top shared_dot12 -part xc7z020clg484-2 -mode out_of_context
create_clock -name algorithm_clk -period 20.341 [get_ports clk]
set_input_delay 2.0 -clock algorithm_clk [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_output_delay 2.0 -clock algorithm_clk [get_ports -filter {DIRECTION == OUT}]
opt_design
place_design
route_design
report_utilization -file dot12_utilization.rpt
report_timing_summary -file dot12_timing.rpt
report_drc -file dot12_drc.rpt
write_checkpoint -force dot12_routed.dcp
exit
