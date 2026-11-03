from pathlib import Path
P=Path(__file__).resolve().parent
p=P/'sixmic_pl_top.sv';s=p.read_text()
assert 'mode_for_window <= config_mode;' in s
s=s.replace('mode_for_window <= config_mode;','mode_for_window <= config_mode && adaptive_use_cnn;')
s=s.replace('wire reference_ready, reference_noisy;','wire reference_ready, reference_noisy;\n    wire adaptive_use_cnn;')
s=s.replace('    pl_noise_floor reference_floor(','''    pl_adaptive_mode adaptive_mode(.clk(clk), .rst_n(reset_processing_n), .arm(short_arm),
        .reference_qualified(spatial_reference_valid), .short_valid(short_valid), .short_ready(short_ready),
        .short_channel(short_channel), .short_bin(short_bin), .short_real(short_real), .short_imag(short_imag),
        .use_cnn(adaptive_use_cnn));
    pl_noise_floor reference_floor(''')
s=s.replace('.background_enabled(config_mode),','.background_enabled(cnn_required),').replace('.background_ratio_float(config_mode?', '.background_ratio_float(cnn_required?')
p.write_text(s)
print('Adaptive mode applies to both CNN and MUSIC whitening, with matched hysteresis.')
