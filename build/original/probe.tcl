set root C:/Users/sunxi/Desktop/sixmic3D
set out $root/deployment/echo_separate_mic_clocks_20261026
set_param general.maxThreads 2
open_checkpoint $root/deployment/releases/SixMic3D_PL_Analysis_RC1_RecoveryFix_20261024/hardware/routed.dcp
foreach name {mic_sck mic_ws} {
    set port [get_ports $name]
    set net [get_nets -of_objects $port]
    puts "CLOCK_PORT $name NET $net"
    puts "CLOCK_BUF [get_cells -of_objects [get_pins -of_objects $net]]"
}
help create_port
help create_cell
help place_ports
help route_design
help write_hw_platform
puts PROBE_DONE
close_design
