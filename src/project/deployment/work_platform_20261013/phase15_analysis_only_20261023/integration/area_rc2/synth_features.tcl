set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
set out $root/tmp/p26_feature_area
file mkdir $out
foreach version {baseline candidate} {
    create_project -in_memory -part xc7z020clg484-2
    set_param general.maxThreads 2
    if {$version eq "baseline"} {read_verilog -sv $here/baseline_fft_event_features.sv} else {read_verilog -sv $here/fft_event_features.sv}
    synth_design -mode out_of_context -top fft_event_features -part xc7z020clg484-2
    create_clock -name compute -period 20 [get_ports clk]
    opt_design
    report_utilization -file $out/${version}_utilization.rpt
    write_checkpoint -force $out/${version}.dcp
    close_project
}
puts FEATURE_AREA_COMPARE_DONE
