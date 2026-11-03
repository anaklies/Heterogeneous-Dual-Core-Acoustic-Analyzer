set here [file dirname [file normalize [info script]]]
cd $here
create_project -force dot_sim $here/cache/dot_sim -part xc7z020clg484-2
read_verilog -sv [file normalize ../../rtl/compute/shared_dot12.sv]
add_files -fileset sim_1 tb_shared_dot12.sv
set_property include_dirs [list $here] [get_filesets sim_1]
set_property top tb_shared_dot12 [get_filesets sim_1]
set_property xsim.simulate.runtime all [get_filesets sim_1]
launch_simulation
close_sim
set f [open $here/cache/dot_sim/dot_sim.sim/sim_1/behav/xsim/simulate.log r]
set result [read $f]
close $f
if {[string first SHARED_DOT12_PASS $result]<0 || [string first {Fatal:} $result]>=0} {error "RTL numerical test did not pass"}
exit
