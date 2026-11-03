set root C:/Users/sunxi/Desktop/sixmic3D_fpga
set stage C:/Users/sunxi/Desktop/sixmic3D/deployment/environment_20261009
open_project [file join $root sixmic3D sixmic3D.xpr]
foreach f {air_sound_speed.sv air_speed_correction.sv pl_adaptive_mode.sv} {
    set p [file join $root pl rtl $f]
    if {[llength [get_files -quiet $p]]==0} {add_files -norecurse $p}
}
set m [file join $root pl coeff air_delta_coeff.mem]
if {[llength [get_files -quiet $m]]==0} {add_files -norecurse $m}
set_property file_type {Memory Initialization Files} [get_files $m]
update_compile_order -fileset sources_1
synth_design -top sixmic_board_top -part xc7z020clg484-2 -directive AreaOptimized_high -resource_sharing on -flatten_hierarchy full
opt_design
report_utilization -file [file join $stage release_shared_utilization.rpt]
report_drc -file [file join $stage release_shared_drc.rpt]
write_checkpoint -force [file join $stage release_shared_opt.dcp]
close_project
