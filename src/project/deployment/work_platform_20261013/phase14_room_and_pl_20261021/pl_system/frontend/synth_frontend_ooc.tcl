set root [file normalize [file join [file dirname [info script]] ../../..]]
# root is deployment/work_platform_20261013, resolve the actual workspace below.
set workspace [file normalize [file join $root ../..]]
set out [file join $workspace tmp p16_frontend_ooc]
set repo [file join $workspace tmp p16_frontend_split hls impl ip]
create_project frontend_ooc $out -part xc7z020clg484-2 -force
set_property ip_repo_paths [list $repo] [current_project]
update_ip_catalog
create_ip -vlnv xilinx.com:hls:acoustic_frontend_pipeline:1.0 -module_name frontend_hw
generate_target all [get_ips frontend_hw]
synth_ip [get_ips frontend_hw]
open_checkpoint [file join $out frontend_ooc.gen sources_1 ip frontend_hw frontend_hw.dcp]
set unresolved [get_cells -hier -filter {IS_BLACKBOX == 1}]
if {[llength $unresolved] != 0} {error "Unresolved black boxes: $unresolved"}
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out utilization_hierarchical.rpt]
report_timing_summary -file [file join $out timing_summary.rpt]
write_checkpoint -force [file join $out frontend_synth.dcp]
close_project
