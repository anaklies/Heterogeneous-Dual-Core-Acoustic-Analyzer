set out C:/Users/sunxi/Desktop/sixmic3D/deployment/echo_vivado_screenshots_20261101
open_project C:/Users/sunxi/Desktop/sixmic3D/tmp/echo_separate_io_20261026/instrument_board/instrument_board.xpr
open_run impl_1
report_utilization -name ECHO_FINAL_UTILIZATION -file $out/current_utilization.rpt
set bd [get_files -all *design_1.bd]
open_bd_design $bd
puts "ECHO_SCREENSHOT_READY"
catch {help write_bd_layout} msg
set f [open $out/bd_export_help.txt w]; puts $f $msg; close $f
