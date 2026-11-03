set stage C:/Users/sunxi/Desktop/sixmic3D/deployment/environment_20261009
open_checkpoint [file join $stage final_release_opt.dcp]
opt_design -directive ExploreSequentialArea
report_utilization -file [file join $stage sequential_utilization.rpt]
report_drc -file [file join $stage sequential_drc.rpt]
write_checkpoint -force [file join $stage sequential_opt.dcp]
