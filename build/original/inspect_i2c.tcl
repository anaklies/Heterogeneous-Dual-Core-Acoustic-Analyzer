set root C:/Users/sunxi/Desktop/sixmic3D
set_param general.maxThreads 2
open_checkpoint $root/deployment/releases/SixMic3D_PL_Analysis_RC1_RecoveryFix_20261024/hardware/routed.dcp
foreach name {sensor_scl sensor_sda} {
    set pad [get_nets -of_objects [get_ports $name]]
    foreach cell [get_cells -of_objects [get_pins -of_objects $pad]] {
        puts "I2C_CELL $cell REF [get_property REF_NAME $cell]"
        foreach pin [get_pins -of_objects $cell] {puts "I2C_PIN $pin NET [get_nets -of_objects $pin]"}
    }
}
foreach cell [get_cells -hier -regexp {.*bus/addr_reg\[4\]}] {
    puts "I2C_SELECTOR $cell [get_nets -of_objects [get_pins $cell/Q]]"
}
puts INSPECT_DONE
