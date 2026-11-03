from pathlib import Path
P=Path(__file__).resolve().parent
s=(P/'sensor_i2c_hub.sv').read_text()
s=s.replace('reg [TEMPW - 1:0] temp_age;', 'reg [7:0] temp_age;').replace('reg [IMUW - 1:0] imu_age;', 'reg [4:0] imu_age;')
s=s.replace('reg [TPW-1:0] temp_poll_count;', 'reg [5:0] temp_poll_count;').replace('reg [TW-1:0] pressure_poll_count;', 'reg [3:0] pressure_poll_count;').replace('reg [TEMPW-1:0] pressure_age;', 'reg [5:0] pressure_age;')
s=s.replace('CLK_HZ * 15','150').replace('CLK_HZ * 5','50').replace('CLK_HZ * 2','20')
s=s.replace('pressure_poll_count <= CLK_HZ;', 'pressure_poll_count <= 10;').replace('pressure_poll_count >= CLK_HZ','pressure_poll_count >= 10')
s=s.replace('    reg pressure_seen;', '    reg pressure_seen;\n    wire poll_tick = poll_count >= CLK_HZ / 10;')
start=s.index('            if (temp_age < 150)temp_age <= temp_age + 1;')
end=s.index('            case',start)
s=s[:start]+'''            // A single 100 ms tick drives all slow age/poll counters.
            // It runs even if an I2C transaction fails or remains busy.
            if (poll_tick)
            begin
                poll_count <= 0;
                if (temp_age < 150)temp_age <= temp_age + 1;
                if (imu_age < 20)imu_age <= imu_age + 1;
                if (pressure_age < 50)pressure_age <= pressure_age + 1;
                if (temp_poll_count < 50)temp_poll_count <= temp_poll_count + 1;
                if (pressure_poll_count < 10)pressure_poll_count <= pressure_poll_count + 1;
            end
            else poll_count <= poll_count + 1;
''' +s[end:]
s=s.replace('IDLE:if (poll_count >= CLK_HZ / 10 && !busy)','IDLE:if (poll_tick && !busy)')
(P/'sensor_i2c_hub.sv').write_text(s)
print('Shared 100ms timer; retained 5s SHT, 1s pressure, 2/5/15s expiry.')
