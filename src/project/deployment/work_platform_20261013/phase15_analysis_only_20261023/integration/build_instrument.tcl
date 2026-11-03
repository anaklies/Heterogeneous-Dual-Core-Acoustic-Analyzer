set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../..]
set out $root/tmp/p21_instrument_synth
file mkdir $out
file copy -force $root/deployment/environment_20261009/air_coeff.mem $out/air_coeff.mem
cd $out
create_project instrument $out/project -part xc7z020clg484-2 -force
set_param general.maxThreads 2
set h [open $root/tmp/p20_scalar/hls/impl/ip/drivers/scalar_engine_v1_0/src/xscalar_engine_hw.h r]
set abi [read $h];close $h
if {![string match "*ADDR_STATUS_DATA*0x58*" $abi] || ![string match "*EXPECTED_SESSION*" $abi]} {error "Scalar IP ABI is stale; rebuild nine-argument session/config/frame kernel first"}
foreach build {p20_scalar p20_stream_fft} {
 set hdl $root/tmp/$build/hls/impl/ip/hdl
 read_verilog [glob $hdl/verilog/*.v]
 foreach folder [glob -types d $hdl/ip/*] {
  foreach ipfile [glob -nocomplain $folder/*.xci] {read_ip $ipfile}
 }
}
generate_target synthesis [get_ips]
# HLS child XCIs are synthesized in-context with the connected runtime.
set legacy $root/deployment/work_platform_20261013/phase14_room_and_pl_20261021/pl_system
read_verilog -sv [list $legacy/hls_job_bridge.sv $legacy/axi_activity_guard.sv $root/deployment/work_platform_20261013/phase13_pl_port_20261021/rtl/control/pcm_axi_ring_writer.sv]
read_verilog [list $root/pl/board/i2s_timing_gen.v $root/pl/board/i2s_rx_6ch.v]
foreach name {sample_cdc pcm_capture window_pool window_dma analysis_scheduler stream_job_bridge audio_pipeline analysis_runtime} {read_verilog -sv $here/$name.sv}
read_verilog -sv $root/deployment/work_platform_20261013/phase13_pl_port_20261021/rtl/control/mic_health.sv
read_verilog -sv $here/../event/event_power_detector.sv
foreach name {runtime_control instrument_sensors event_recorder fft_event_features raw_cursor} {read_verilog -sv $here/control/$name.sv}
foreach name {sensor_i2c_hub i2c_transaction_master air_sound_speed} {read_verilog -sv $root/deployment/environment_20261009/$name.sv}
read_verilog -sv $here/instrument_top.sv
synth_design -top instrument_top -part xc7z020clg484-2 -mode out_of_context
create_clock -name compute -period 20 [get_ports clk_compute]
create_clock -name audio -period 20.340909 [get_ports clk_audio]
set_clock_groups -asynchronous -group [get_clocks compute] -group [get_clocks audio]
report_utilization -file $here/results/instrument_utilization.rpt
report_utilization -hierarchical -file $here/results/instrument_hierarchy.rpt
report_timing_summary -file $here/results/instrument_synth_timing.rpt
report_cdc -file $here/results/instrument_cdc.rpt
write_checkpoint -force $out/instrument_synth.dcp
puts INSTRUMENT_SYNTH_DONE

