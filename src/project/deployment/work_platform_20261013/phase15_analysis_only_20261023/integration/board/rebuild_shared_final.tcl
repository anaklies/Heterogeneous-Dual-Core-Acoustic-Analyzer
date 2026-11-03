set root C:/Users/sunxi/Desktop/sixmic3D
set here $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration
open_project $root/tmp/p24_shared_instrument_board/project/instrument_board.xpr
set hdl $root/tmp/p20_scalar/hls/impl/ip/hdl
foreach item [get_files -all] {if {[string match -nocase "*/tmp/p20_scalar/hls/impl/ip/hdl/verilog/*" $item] && ![file exists $item]} {remove_files $item}}
foreach item [glob $hdl/verilog/*.v] {if {[llength [get_files -quiet $item]]==0} {add_files $item}}
foreach item [glob -nocomplain $hdl/verilog/*.vh] {
 if {[llength [get_files -quiet $item]]==0} {add_files $item}
 set_property file_type {Verilog Header} [get_files $item]
}
foreach folder [glob -types d $hdl/ip/*] {foreach item [glob -nocomplain $folder/*.xci] {if {[llength [get_ips -quiet [file rootname [file tail $item]]]]==0} {read_ip $item}}}
if {[llength [get_files -quiet $here/control/raw_cursor.sv]]==0} {add_files $here/control/raw_cursor.sv}
update_compile_order -fileset sources_1
reset_run synth_1
close_project
source $here/board/implement_shared.tcl
