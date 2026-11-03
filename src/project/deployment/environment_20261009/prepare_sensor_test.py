from pathlib import Path
P=Path(__file__).resolve().parent;FPGA=P.parents[2]/'sixmic3D_fpga'
s=(FPGA/'pl/sim/tb_sensor_i2c_hub.sv').read_text()
s=s.replace('wire temperature_valid, orientation_valid;','wire temperature_valid, orientation_valid, pressure_valid;\n    wire [15:0] humidity_raw;\n    wire [31:0] pressure_pa;\n    integer ticks=0,last_measurement=-1,measurements=0;')
s=s.replace('reg bad_temp = 0, bad_imu = 0;','reg bad_temp = 0, bad_imu = 0, bad_pressure = 0;')
s=s.replace('if (dut.state == 4)', '''ticks=ticks+1;
        if (dut.state == 8)
        begin
            fake_done=1;fake_error=dut.address==7'h44;
            if(dut.write_data[15:0]!=16'h6630)$fatal(1,"heater disable command");
        end
        if (dut.state == 7)
        begin
            if(dut.write_count!=1 || dut.write_data[7:0]!=8'h45 || dut.read_count!=4 || dut.address!=7'h50)
                $fatal(1,"IMU pressure register/length");
            fake_done=1;fake_error=bad_pressure;fake_read=128'd101325;
        end
        if (dut.state == 4)''')
s=s.replace("fake_error = dut.address == 7'h44;","fake_error = 0;\n            if(last_measurement>=0 && ticks-last_measurement<500000)$fatal(1,\"SHT measured too frequently\");\n            last_measurement=ticks;measurements=measurements+1;")
s=s.replace("16'h0024","16'h0b24")
s=s.replace('if (temperature_centi != 2500 || qw != 32767 || roll != 16\'h10)',
    'if (temperature_centi != 2500 || humidity_raw != 32768 || pressure_pa != 101325 || !pressure_valid || qw != 32767 || roll != 16\'h10)')
s=s.replace('bad_imu = 1;','bad_imu = 1;bad_pressure=1;')
s=s.replace('repeat(250000)','repeat(600000)').replace('repeat(300000)','repeat(1000000)')
s=s.replace('if (orientation_valid)', 'if (pressure_valid || !sensor_faults[5])$fatal(1,"bad pressure remained usable");\n        if (orientation_valid)')
s=s.replace('bad_imu = 0;','bad_imu = 0;bad_pressure=0;')
s=s.replace('#15000000;','#40000000;')
s=s.replace('PASS: IMU registers,','PASS: 5-second SHT cadence, heater off, medium repeatability, pressure/fallback, IMU registers,')
(P/'tb_sensor_environment.sv').write_text(s)
print('Sensor integrity, cadence, independent failure and recovery bench prepared.')
