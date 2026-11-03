set evidence [file dirname [file normalize [info script]]]
set root C:/Users/sunxi/Desktop/sixmic3D_fpga
set reportdir C:/Users/sunxi/Desktop/sixmic3D/deployment/environment_20261009
file mkdir $reportdir
open_project [file join $root sixmic3D sixmic3D.xpr]
set_property ip_repo_paths [list [file join $root pl ip track_sources_environment_final_20261009] [file join $root pl hls build features_band hls impl ip] [file join $root pl hls build music_final hls impl ip]] [current_project]
update_ip_catalog
upgrade_ip -quiet [get_ips track_sources_global_0]
reset_target all [get_ips track_sources_global_0]
generate_target all [get_ips track_sources_global_0]
create_ip_run [get_ips track_sources_global_0]
set run [get_runs track_sources_global_0_synth_1]
set_property STEPS.SYNTH_DESIGN.ARGS.DIRECTIVE AreaOptimized_high $run
set_property STEPS.SYNTH_DESIGN.ARGS.RESOURCE_SHARING on $run
reset_run $run
launch_runs $run -jobs 1
wait_on_run $run
if {![string match "*Complete*" [get_property STATUS $run]]} {error "Recovery tracker IP synthesis failed"}
update_compile_order -fileset sources_1
synth_design -top sixmic_board_top -part xc7z020clg484-2 -directive AreaOptimized_high
opt_design
report_utilization -file [file join $reportdir final_release_opt_utilization.rpt]
report_drc -file [file join $reportdir final_release_opt_drc.rpt]
write_checkpoint -force [file join $reportdir final_release_opt.dcp]
close_project
