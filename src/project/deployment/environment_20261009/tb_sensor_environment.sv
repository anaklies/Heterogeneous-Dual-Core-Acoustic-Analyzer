`timescale 1ns/1ps

module tb_sensor_i2c_hub;

    wire [7:0] sensor_faults;
    reg clk = 0;

    always #5 clk = ~clk;
    reg rst_n = 0;
    tri1 scl, sda;
    wire signed [15:0] temperature_centi, qw, qx, qy, qz, roll, pitch, yaw;
    wire temperature_valid, orientation_valid, pressure_valid, orientation_update;
    wire [15:0] humidity_raw;
    wire [31:0] pressure_pa;
    integer ticks=0,last_measurement=-1,measurements=0;
    wire [15:0] error_count;
    reg fake_done = 0, fake_error = 0;
    reg [127:0] fake_read = 0;
    reg bad_temp = 0, bad_imu = 0, bad_pressure = 0;
    sensor_i2c_hub #(.CLK_HZ(100000)) dut(.*);
    function automatic[7:0] crc(input [15:0] v);
    reg [7:0] a;
    begin
        a = 8'hff;
        for (integer i = 0;i < 2;i++)
        begin
            a = a ^ (i == 0?v[15:8]:v[7:0]);
            for (integer j = 0;j < 8;j++)a = a[7]?(a << 1) ^ 8'h31:a << 1;
        end
        crc = a;
    end
    endfunction
    // Transaction-master waveforms have their separate physical I2C test.
    // This bench injects completed transactions to exercise hub integrity/staleness.
    initial
    begin
        force dut.done = fake_done;
        force dut.error = fake_error;
        force dut.read_data = fake_read;
        force dut.busy = 1'b0;
        #100;
        rst_n = 1;
    end

    always @(negedge clk)
    begin
        fake_done = 0;
        fake_error = 0;
        ticks=ticks+1;
        if (dut.state == 10)
        begin
            fake_done=1;fake_error=dut.address==7'h44;
            if(dut.write_data[15:0]!=16'h9330)$fatal(1,"stop periodic command");
        end
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
        if (dut.state == 4)
        begin
            fake_done = 1;
            fake_error = 0;
            if(last_measurement>=0 && ticks-last_measurement<500000)$fatal(1,"SHT measured too frequently");
            last_measurement=ticks;measurements=measurements+1;
            if (dut.write_count != 2 || dut.write_data[15:0] != 16'h0b24)$fatal(1, "SHT command byte order");
        end
        if (dut.state == 2)
        begin
            fake_read = 128'h003000200010;
            fake_done = 1;
        end
        if (dut.state == 3)
        begin
            fake_read = bad_imu?0:128'h0000000000007fff;
            fake_done = 1;
        end
        if (dut.state == 6)
        begin
            fake_read = 0;
            fake_read[7:0] = 8'h66;
            fake_read[15:8] = 8'h66;
            fake_read[23:16] = bad_temp?8'h00:crc(16'h6666);
            fake_read[31:24] = 8'h80;
            fake_read[39:32] = 8'h00;
            fake_read[47:40] = crc(16'h8000);
            fake_done = 1;
        end
    end
    initial
    begin
        if (dut.crc16word(16'hbeef) != 8'h92)$fatal(1, "SHT datasheet CRC example");
        wait(temperature_valid && orientation_valid);
        #20;
        if (temperature_centi != 2500 || humidity_raw != 32768 || pressure_pa != 101325 || !pressure_valid || qw != 32767 || roll != 16'h10)$fatal(1, "valid sensor decoding");
        if (dut.sht_selected != 7'h45)$fatal(1, "SHT alternate address");
        bad_temp = 1;
        bad_imu = 1;bad_pressure=1;
        repeat(600000)@(posedge clk);
        if (temperature_centi != 2500 || qw != 32767 || error_count == 0)$fatal(1,
            "bad CRC or quaternion replaced last good data");
        if (!sensor_faults[2] || !sensor_faults[3])$fatal(1, "CRC and quaternion fault details missing");
        if (pressure_valid || !sensor_faults[5])$fatal(1,"bad pressure remained usable");
        if (orientation_valid)$fatal(1, "stale IMU remained valid");
        repeat(1000000)@(posedge clk);
        if (temperature_valid)$fatal(1, "stale temperature remained valid");
        bad_temp = 0;
        bad_imu = 0;bad_pressure=0;
        wait(temperature_valid && orientation_valid);
        #20;
        if (temperature_centi != 2500 || sensor_faults[3:0] != 0)$fatal(1,
            "sensor recovery or fault flags failed");
        $display("PASS: 5-second SHT cadence, heater off, medium repeatability, pressure/fallback, IMU registers, SHT30 alternate address, command, CRC and endian, last-good retention, staleness and recovery");
        $finish;
    end
    initial
    begin
        #40000000;
        $fatal(1, "sensor hub timeout");
    end
endmodule
