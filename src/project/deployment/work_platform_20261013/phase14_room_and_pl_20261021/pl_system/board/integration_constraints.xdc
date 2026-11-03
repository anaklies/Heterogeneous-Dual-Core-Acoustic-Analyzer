# This file is intentionally not a timing waiver.
# PS FCLK0, the acoustic MMCM75MHz and SmartConnect CDC get their generated
# clock/CDC constraints from their actual IP. Do not duplicate create_clock on
# those generated clocks and do not blanket-false-path data connections.
# The physical board top must inherit verified package pins and real external
# I2S/I2C/HDMI timing constraints. It is not created by create_board_bd.tcl.
# Audio capture clock remains the verified clock; do not change I2S sample
# timing when switching the NN compute clock to75MHz.
