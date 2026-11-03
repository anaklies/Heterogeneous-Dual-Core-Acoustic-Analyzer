from pathlib import Path
P=Path(__file__).resolve().parent
s=(P/'sensor_i2c_hub.sv').read_text()
s=s.replace('output wire temperature_valid,','output wire temperature_valid,\n    output reg [15:0] humidity_raw,\n    output reg [31:0] pressure_pa,\n    output wire pressure_valid,')
s=s.replace('TEMP_READ = 6;','TEMP_READ = 6, PRESSURE = 7, HEATER_OFF = 8, HEATER_WAIT = 9;').replace('reg [2:0] state;','reg [3:0] state;')
s=s.replace('CLK_HZ * 5','CLK_HZ * 15')
s=s.replace('reg [3:0] temp_divider;', '''localparam TPW = $clog2(CLK_HZ * 5 + 1);
    reg [TPW-1:0] temp_poll_count;
    reg [TW-1:0] pressure_poll_count;
    reg [TEMPW-1:0] pressure_age;
    reg pressure_seen;''')
s=s.replace('assign orientation_valid =', 'assign pressure_valid = pressure_seen && pressure_age < CLK_HZ * 5;\n    assign orientation_valid =')
s=s.replace('temp_divider <= 9;', '''humidity_raw <= 0;
            pressure_pa <= 0;
            pressure_seen <= 0;
            pressure_age <= CLK_HZ * 5;
            temp_poll_count <= CLK_HZ * 5;
            pressure_poll_count <= CLK_HZ;''')
s=s.replace('if (poll_count < CLK_HZ / 10)', '''if (pressure_age < CLK_HZ * 5)pressure_age <= pressure_age + 1;
            if (temp_poll_count < CLK_HZ * 5)temp_poll_count <= temp_poll_count + 1;
            if (pressure_poll_count < CLK_HZ)pressure_poll_count <= pressure_poll_count + 1;
            if (poll_count < CLK_HZ / 10)''')
start=s.index('                    if (temp_divider == 9)')
end=s.index('                TEMP_CMD:if (done)',start)
s=s[:start]+'''                    if (pressure_poll_count >= CLK_HZ)
                    begin
                        pressure_poll_count <= 0;
                        address <= IMU_ADDRESS;
                        write_count <= 1;
                        write_data <= 32'h45;
                        read_count <= 4;
                        start <= 1;
                        state <= PRESSURE;
                    end
                    else finish_poll();
                end
                PRESSURE:if (done)
                begin
                    sensor_faults[5] <= error || read_data[31:0] < 30000 || read_data[31:0] > 120000;
                    if (!error && read_data[31:0] >= 30000 && read_data[31:0] <= 120000)
                    begin
                        pressure_pa <= read_data[31:0];
                        pressure_seen <= 1;
                        pressure_age <= 0;
                    end
                    else if (error_count != 65535)error_count <= error_count + 1;
                    finish_poll();
                end
                HEATER_OFF:if (done)
                begin
                    sensor_faults[1] <= error;
                    if (error)
                    begin
                        if (error_count != 65535)error_count <= error_count + 1;
                        if (AUTO_SHT_ADDRESS) sht_selected <= sht_selected ^ 7'h01;
                        state <= IDLE;
                    end
                    else
                    begin
                        timer <= 0;
                        state <= HEATER_WAIT;
                    end
                end
                HEATER_WAIT:if (timer >= CLK_HZ / 1000)
                begin
                    address <= sht_selected;
                    write_count <= 2;
                    write_data <= 32'h0b24;
                    read_count <= 0;
                    start <= 1;
                    state <= TEMP_CMD;
                end
                else timer <= timer + 1;
''' +s[end:]
s=s.replace('CLK_HZ / 50','CLK_HZ / 100')
s=s.replace('temperature_centi <= converted_temperature[15:0];','temperature_centi <= converted_temperature[15:0];\n                        humidity_raw <= {read_data[31:24], read_data[39:32]};')
task='''    // SHT30: heater disabled, medium-repeatability single shot every five seconds.
    // IMU orientation remains at 10 Hz; pressure is independent at 1 Hz.
    task automatic finish_poll;
        begin
            if (temp_poll_count >= CLK_HZ * 5)
            begin
                temp_poll_count <= 0;
                address <= sht_selected;
                write_count <= 2;
                write_data <= 32'h6630;
                read_count <= 0;
                start <= 1;
                state <= HEATER_OFF;
            end
            else state <= IDLE;
        end
    endtask
'''
s=s.replace('    always @(posedge clk)\n',task+'\n    always @(posedge clk)\n',1)
(P/'sensor_i2c_hub.sv').write_text(s)
print('Prepared low-rate SHT30 and IMU pressure candidate; original FPGA files unchanged.')
