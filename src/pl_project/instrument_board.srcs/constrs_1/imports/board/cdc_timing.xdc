# This boundary is an actual asynchronous, Gray-pointer FIFO, not a direct bus.
# Audio has its own fractional MMCM. Both synchronizer stages and immutable
# dual-clock FIFO storage were verified in the capture/CDC tests.
# Keep all compute<->PS, HDMI and data timing active.
set audio_domain [get_clocks clk_out1_design_1_audio_clock_0]
set compute_domain [get_clocks clk_out2_design_1_clk_wiz_acoustic_0]
set_clock_groups -name sampled_audio_async -asynchronous -group $audio_domain -group $compute_domain
set fifo_root design_1_i/instrument/inst/u_core/runtime/pipeline/capture/crossing
set write_gray [get_cells -hier -filter "NAME =~ $fifo_root/wg_reg* && IS_SEQUENTIAL"]
set write_sync [get_cells -hier -filter "NAME =~ $fifo_root/wg1_reg* && IS_SEQUENTIAL"]
set read_gray [get_cells -hier -filter "NAME =~ $fifo_root/rg_reg* && IS_SEQUENTIAL"]
set read_sync [get_cells -hier -filter "NAME =~ $fifo_root/rg1_reg* && IS_SEQUENTIAL"]
# Skew is an independent timing assertion; no max_delay hidden by clock groups.
# 20ns is no larger than either pointer update period (20 and20.341ns).
set_bus_skew 20.0 -from $write_gray -to $write_sync
set_bus_skew 20.0 -from $read_gray -to $read_sync
