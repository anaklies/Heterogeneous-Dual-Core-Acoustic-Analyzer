set root C:/Users/sunxi/Desktop/sixmic3D
set here $root/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration
open_checkpoint $root/tmp/p22_instrument_board_v4/routed.dcp
set_param general.maxThreads 2
report_control_sets -verbose -file $here/results/current_control_sets.rpt
set groups [dict create]
foreach cell [get_cells -hier -filter {REF_NAME == FDRE || REF_NAME == FDSE}] {
 if {[get_property ASYNC_REG $cell]==1} {continue}
 set key ""
 foreach pin {C CE R S} {
  set p [get_pins -quiet $cell/$pin]
  if {[llength $p]} {append key "|$pin:[get_nets -of_objects $p]"}
 }
 dict lappend groups $key $cell
}
set fp [open $here/results/low_fanout_control_groups.csv w]
puts $fp "registers,representative"
set small4 0;set regs4 0;set small8 0;set regs8 0
set selected {}
dict for {key cells} $groups {
 set n [llength $cells]
 if {$n<=4} {incr small4;incr regs4 $n}
 if {$n<=8} {incr small8;incr regs8 $n}
 if {$n<=8} {puts $fp "$n,[lindex $cells 0]"}
}
close $fp
puts "CONTROL_AUDIT groups=[dict size $groups] small4=$small4 regs4=$regs4 small8=$small8 regs8=$regs8"
