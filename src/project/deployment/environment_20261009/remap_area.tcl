set stage C:/Users/sunxi/Desktop/sixmic3D/deployment/environment_20261009
open_checkpoint [file join $stage compact_environment_opt.dcp]
opt_design -directive ExploreWithRemap
report_utilization -file [file join $stage remap_utilization.rpt]
report_drc -file [file join $stage remap_drc.rpt]
write_checkpoint -force [file join $stage remap_opt.dcp]
