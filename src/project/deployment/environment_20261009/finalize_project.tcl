set root C:/Users/sunxi/Desktop/sixmic3D_fpga
set stage C:/Users/sunxi/Desktop/sixmic3D/deployment/environment_20261009
open_project [file join $root sixmic3D sixmic3D.xpr]
set s [get_runs synth_1]
set_property STEPS.SYNTH_DESIGN.ARGS.DIRECTIVE AreaOptimized_high $s
set_property STEPS.SYNTH_DESIGN.ARGS.RESOURCE_SHARING on $s
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY full $s
set_property STEPS.OPT_DESIGN.ARGS.DIRECTIVE ExploreSequentialArea [get_runs impl_1]
update_compile_order -fileset sources_1
close_project
open_checkpoint [file join $stage final_borrow_opt.dcp]
opt_design -directive ExploreSequentialArea
report_utilization -file [file join $stage final_release_sequential_utilization.rpt]
report_drc -file [file join $stage final_release_sequential_drc.rpt]
write_checkpoint -force [file join $stage final_release_sequential_opt.dcp]
