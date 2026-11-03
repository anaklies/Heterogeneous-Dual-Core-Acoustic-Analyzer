# Recovery after synth_ip succeeded but the original script requested a run
# object that this custom IP flow did not create. Do not synthesize again.
set platform [file normalize [file join [file dirname [info script]] ../../..]]
set workspace [file normalize [file join $platform ../..]]
set out [file join $workspace tmp p16_frontend_ooc]
open_checkpoint [file join $out frontend_ooc.gen sources_1 ip frontend_hw frontend_hw.dcp]
set unresolved [get_cells -hier -filter {IS_BLACKBOX == 1}]
set fp [open [file join $out blackbox_check.txt] w]
puts $fp "UNRESOLVED_BLACKBOX_COUNT=[llength $unresolved]"
close $fp
if {[llength $unresolved] != 0} {error "Unresolved black boxes: $unresolved"}
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out utilization_hierarchical.rpt]
report_timing_summary -file [file join $out timing_summary.rpt]
write_checkpoint -force [file join $out frontend_synth.dcp]
close_design
