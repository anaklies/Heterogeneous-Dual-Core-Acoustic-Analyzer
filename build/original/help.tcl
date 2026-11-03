foreach command {create_port create_cell connect_net place_ports route_design write_hw_platform} {
    puts [help $command]
}
