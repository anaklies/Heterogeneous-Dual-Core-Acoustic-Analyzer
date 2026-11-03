from pathlib import Path
P=Path(__file__).resolve().parent
p=P/'imu_rotation_q16.sv';s=p.read_text()
s=s.replace('wire [34:0] trial = {remainder, dividend[47]};','''wire [34:0] trial = {remainder, dividend[47]};
    (* use_dsp="yes" *) wire signed [35:0] division_difference = $signed({1'b0,trial}) - $signed({2'b0,divisor});
    wire division_accept = !division_difference[35];''')
s=s.replace('trial >= divisor','division_accept').replace('trial - divisor','division_difference[33:0]')
p.write_text(s)
p=P/'air_speed_correction.sv';s=p.read_text()
s=s.replace('wire [18:0] trial={remainder,dividend[34]};','''wire [18:0] trial={remainder,dividend[34]};
    (* use_dsp="yes" *) wire signed [19:0] division_difference=$signed({1'b0,trial})-$signed({3'b0,divisor});
    wire division_accept=!division_difference[19];''')
s=s.replace('trial>=divisor','division_accept').replace('trial-divisor','division_difference[17:0]')
p.write_text(s)
print('Borrow bit shares exact compare/subtract in two restoring dividers; no numerical or cycle change.')
