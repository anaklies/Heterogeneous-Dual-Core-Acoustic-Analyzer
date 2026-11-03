set here [file dirname [file normalize [info script]]]
set root [file normalize $here/../../../../..]
open_project $root/tmp/p17_board_kernels/project/board_kernels.xpr
set fp [open $here/synthesis_options.txt w]
foreach property [list_property [get_runs synth_1]] {
    if {[string match "*SYNTH_DESIGN*" $property]} {
        puts $fp "$property = [get_property $property [get_runs synth_1]]"
    }
}
close $fp
close_project
