set root C:/Users/sunxi/Desktop/sixmic3D
set here $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration
open_project $root/tmp/p22_instrument_board_v4/project/instrument_board.xpr
set hdl $root/tmp/p20_scalar/hls/impl/ip/hdl
foreach item [get_files -all] {
 if {[string match "*/tmp/p20_scalar/hls/impl/ip/hdl/verilog/*" $item] && ![file exists $item]} {remove_files $item}
}
foreach item [glob $hdl/verilog/*.v] {if {[llength [get_files -quiet $item]]==0} {add_files $item}}
foreach item [glob -nocomplain $hdl/verilog/*.vh] {
 if {[llength [get_files -quiet $item]]==0} {add_files $item}
 set_property file_type {Verilog Header} [get_files $item]
}
foreach folder [glob -types d $hdl/ip/*] {
 foreach item [glob -nocomplain $folder/*.xci] {
  if {[llength [get_ips -quiet [file rootname [file tail $item]]]]==0} {read_ip $item}
 }
}
update_compile_order -fileset sources_1
close_project
set ::env(SIXMIC_EXPLICIT_REBUILD) 1
source $here/board/implement_current.tcl
