# RK-ZYNQ7020-F 40-pin PL header, 3.3 V setting. Connector signal names
# were read from the supplied board silkscreen; verify orientation before wiring.
# One shared I2S clock pair, six independent SD inputs, and one shared I2C bus.
set_property PACKAGE_PIN W12 [get_ports {mic_sd[0]}]
set_property PACKAGE_PIN V12 [get_ports {mic_sd[1]}]
set_property PACKAGE_PIN V9 [get_ports {mic_sd[2]}]
set_property PACKAGE_PIN V10 [get_ports {mic_sd[3]}]
set_property PACKAGE_PIN U9 [get_ports {mic_sd[4]}]
set_property PACKAGE_PIN U10 [get_ports {mic_sd[5]}]
set_property PACKAGE_PIN AB12 [get_ports mic_sck]
set_property PACKAGE_PIN AA12 [get_ports mic_ws]
set_property PACKAGE_PIN Y10 [get_ports sensor_scl]
set_property PACKAGE_PIN Y11 [get_ports sensor_sda]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_sd[0] mic_sd[1] mic_sd[2] mic_sd[3] mic_sd[4] mic_sd[5] mic_sck mic_ws sensor_scl sensor_sda}]
set_property PULLUP true [get_ports {sensor_scl sensor_sda}]
set_property SLEW SLOW [get_ports {mic_sck mic_ws}]

set_property PACKAGE_PIN AA16 [get_ports hdmi_ddc_scl_io]
set_property PACKAGE_PIN AB16 [get_ports hdmi_ddc_sda_io]
set_property IOSTANDARD LVCMOS33 [get_ports hdmi_ddc_scl_io]
set_property IOSTANDARD LVCMOS33 [get_ports hdmi_ddc_sda_io]
set_property PACKAGE_PIN U15 [get_ports {TMDS_data_p[2]}]
set_property PACKAGE_PIN U17 [get_ports {TMDS_data_p[1]}]
set_property PACKAGE_PIN AA17 [get_ports {TMDS_data_p[0]}]
set_property PACKAGE_PIN W16 [get_ports TMDS_clk_p]
set_property IOSTANDARD LVCMOS33 [get_ports hdmi_oen]
set_property PACKAGE_PIN Y18 [get_ports hdmi_oen]

# Board-mounted SPI LCD: vendor verified pin assignment.
set_property PACKAGE_PIN V18 [get_ports {lcd_sck}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_sck}]
set_property PACKAGE_PIN U19 [get_ports {lcd_mosi}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_mosi}]
set_property PACKAGE_PIN AA13 [get_ports {lcd_cs_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_cs_n}]
set_property PACKAGE_PIN W13 [get_ports {lcd_control[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_control[0]}]
set_property PACKAGE_PIN AA18 [get_ports {lcd_control[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_control[1]}]
set_property PACKAGE_PIN Y13 [get_ports {lcd_control[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_control[2]}]

# Defined idle level for unplugged I2S SD inputs.
set_property PULLDOWN true [get_ports {mic_sd[0] mic_sd[1] mic_sd[2] mic_sd[3] mic_sd[4] mic_sd[5]}]

set_property PACKAGE_PIN U11 [get_ports {mic_sck_copy[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_sck_copy[0]}]
set_property SLEW SLOW [get_ports {mic_sck_copy[0]}]

set_property PACKAGE_PIN U12 [get_ports {mic_ws_copy[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_ws_copy[0]}]
set_property SLEW SLOW [get_ports {mic_ws_copy[0]}]

set_property PACKAGE_PIN AB9 [get_ports {mic_sck_copy[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_sck_copy[1]}]
set_property SLEW SLOW [get_ports {mic_sck_copy[1]}]

set_property PACKAGE_PIN AB10 [get_ports {mic_ws_copy[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_ws_copy[1]}]
set_property SLEW SLOW [get_ports {mic_ws_copy[1]}]

set_property PACKAGE_PIN AB11 [get_ports {mic_sck_copy[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_sck_copy[2]}]
set_property SLEW SLOW [get_ports {mic_sck_copy[2]}]

set_property PACKAGE_PIN AA11 [get_ports {mic_ws_copy[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_ws_copy[2]}]
set_property SLEW SLOW [get_ports {mic_ws_copy[2]}]

set_property PACKAGE_PIN W8 [get_ports {mic_sck_copy[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_sck_copy[3]}]
set_property SLEW SLOW [get_ports {mic_sck_copy[3]}]

set_property PACKAGE_PIN V8 [get_ports {mic_ws_copy[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_ws_copy[3]}]
set_property SLEW SLOW [get_ports {mic_ws_copy[3]}]

set_property PACKAGE_PIN W10 [get_ports {mic_sck_copy[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_sck_copy[4]}]
set_property SLEW SLOW [get_ports {mic_sck_copy[4]}]

set_property PACKAGE_PIN W11 [get_ports {mic_ws_copy[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {mic_ws_copy[4]}]
set_property SLEW SLOW [get_ports {mic_ws_copy[4]}]

set_property PACKAGE_PIN AB6 [get_ports imu_scl]
set_property IOSTANDARD LVCMOS33 [get_ports imu_scl]
set_property PULLUP true [get_ports imu_scl]

set_property PACKAGE_PIN AB7 [get_ports imu_sda]
set_property IOSTANDARD LVCMOS33 [get_ports imu_sda]
set_property PULLUP true [get_ports imu_sda]
