set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../..]
set out $root/tmp/p20_runtime_synth
file mkdir $out
create_project runtime $out/project -part xc7z020clg484-2 -force
set_param general.maxThreads 2
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
synth_design -top analysis_runtime -part xc7z020clg484-2 -mode out_of_context
create_clock -name compute -period 20 [get_ports clk_compute]
create_clock -name audio -period 20.340909 [get_ports clk_audio]
set_clock_groups -asynchronous -group [get_clocks compute] -group [get_clocks audio]
report_utilization -file $here/results/runtime_utilization.rpt
report_utilization -hierarchical -file $here/results/runtime_hierarchy.rpt
report_timing_summary -file $here/results/runtime_synth_timing.rpt
report_cdc -file $here/results/runtime_cdc.rpt
write_checkpoint -force $out/runtime_synth.dcp
puts RUNTIME_SYNTH_DONE

