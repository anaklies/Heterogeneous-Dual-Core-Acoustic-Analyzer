`timescale 1ns/1ps
// Protocol: Yahboom build?id=5541&cid=541 (10-axis IMU) and Sensirion SHT3x-DIS.
// IMU 16-bit little-endian register values; SHT words are big-endian + CRC.
// A failed transaction never replaces the last good sample with partial data.

module sensor_i2c_hub #(
    parameter CLK_HZ = 50000000,
    parameter IMU_ADDRESS = 7'h50,
    parameter SHT_ADDRESS = 7'h44,
    parameter AUTO_SHT_ADDRESS = 1
)
(
    input  wire clk,
    input  wire rst_n,
    inout wire scl,
    inout wire sda,
    output reg signed [15:0] temperature_centi,
    output wire temperature_valid,
    output reg [15:0] humidity_raw,
    output reg [31:0] pressure_pa,
    output wire pressure_valid,
    output wire orientation_valid,
    output reg orientation_update,
    output reg signed [15:0] qw,
    output reg signed [15:0] qx,
    output reg signed [15:0] qy,
    output reg signed [15:0] qz,
    output reg signed [15:0] roll,
    output reg signed [15:0] pitch,
    output reg signed [15:0] yaw,
    output reg [7:0] sensor_faults,
    output reg [15:0] error_count
);

    localparam BOOT = 0, IDLE = 1, ANGLES = 2, QUAT = 3, TEMP_CMD = 4, TEMP_DELAY = 5, TEMP_READ = 6, PRESSURE = 7, HEATER_OFF = 8, HEATER_WAIT = 9, STOP_PERIODIC = 10, STOP_WAIT = 11;
    reg [3:0] state;
    localparam TW = $clog2(CLK_HZ + 1) > 0?$clog2(CLK_HZ + 1):1;
    localparam PW = $clog2(CLK_HZ / 10 + 1) > 0?$clog2(CLK_HZ / 10 + 1):1;
    localparam TEMPW = $clog2(150 + 1) > 0?$clog2(150 + 1):1;
    localparam IMUW = $clog2(20 + 1) > 0?$clog2(20 + 1):1;
    reg [TW - 1:0] timer;
    reg [PW - 1:0] poll_count;
    reg [7:0] temp_age;
    reg [4:0] imu_age;
    reg temp_seen, imu_seen;
    reg start;
    reg [6:0] address;
    reg [2:0] write_count;
    reg [31:0] write_data;
    reg [4:0] read_count;
    wire [127:0] read_data;
    wire busy, done, error;
    localparam TPW = $clog2(50 + 1);
    reg [5:0] temp_poll_count;
    reg [3:0] pressure_poll_count;
    reg [5:0] pressure_age;
    reg pressure_seen;
    wire poll_tick = poll_count >= CLK_HZ / 10;
    reg [6:0] sht_selected;
    wire [15:0] raw_temperature = {read_data[7:0], read_data[15:8]};
    // Exact unsigned division by 2^16-1. For N=65536*a+b in this range,
        // floor(N/65535)=a+((a+b)>=65535). Exhaustively checked for all 65536 raw values.
    wire [31:0] temp_scaled = raw_temperature * 32'd17500 + 32'd32767;
    wire [16:0] temp_fold = {1'b0, temp_scaled[31:16]} + {1'b0, temp_scaled[15:0]};
    wire [16:0] temp_quotient = {1'b0, temp_scaled[31:16]} + (temp_fold >= 17'd65535);
    wire signed [31:0] converted_temperature = $signed({15'b0, temp_quotient}) - 32'sd4500;
    wire signed [15:0] next_qw = read_data[15:0], next_qx = read_data[31:16], next_qy = read_data[47:32],
        next_qz = read_data[63:48];
    wire [32:0] norm_q = ($signed(next_qw) * $signed(next_qw)) + ($signed(next_qx) * $signed(next_qx)) +
        ($signed(next_qy) * $signed(next_qy)) + ($signed(next_qz) * $signed(next_qz));
    assign temperature_valid = temp_seen && temp_age < 150;
    assign pressure_valid = pressure_seen && pressure_age < 50;
    assign orientation_valid = imu_seen && imu_age < 20;
    function automatic[7:0] crc16word(input [15:0] word);
    reg [7:0] crc;
    begin
        crc = 8'hff;
        for (integer b = 0;b < 2;b = b + 1)
        begin
            crc = crc ^ (b == 0?word[15:8]:word[7:0]);
            for (integer k = 0;k < 8;k = k + 1)crc = crc[7]?(crc << 1) ^ 8'h31:crc << 1;
        end
        crc16word = crc;
    end
    endfunction
    i2c_transaction_master #(.CLK_HZ(CLK_HZ)) bus(.*);

    // SHT30: heater disabled, medium-repeatability single shot every five seconds.
    // IMU orientation remains at 10 Hz; pressure is independent at 1 Hz.
    task automatic finish_poll;
        begin
            if (temp_poll_count >= 50)
            begin
                temp_poll_count <= 0;
                address <= sht_selected;
                write_count <= 2;
                write_data <= 32'h9330;
                read_count <= 0;
                start <= 1;
                state <= STOP_PERIODIC;
            end
            else state <= IDLE;
        end
    endtask

    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            sensor_faults <= 0;
            state <= BOOT;
            timer <= 0;
            poll_count <= 0;
            temp_age <= 150;
            imu_age <= 20;
            temp_seen <= 0;
            imu_seen <= 0;
            orientation_update <= 0;
            temperature_centi <= 1930;
            qw <= 32767;
            qx <= 0;
            qy <= 0;
            qz <= 0;
            roll <= 0;
            pitch <= 0;
            yaw <= 0;
            sht_selected <= SHT_ADDRESS;
            start <= 0;
            address <= IMU_ADDRESS;
            write_count <= 0;
            write_data <= 0;
            read_count <= 0;
            error_count <= 0;
            humidity_raw <= 0;
            pressure_pa <= 0;
            pressure_seen <= 0;
            pressure_age <= 50;
            temp_poll_count <= 50;
            pressure_poll_count <= 10;
        end

        else
        begin
            start <= 0;
            orientation_update <= 0;
            // A single 100 ms tick drives all slow age/poll counters.
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
            case
                (state)
                BOOT:if (timer >= CLK_HZ)
                begin
                    state <= IDLE;
                    timer <= 0;
                end

                else timer <= timer + 1;
                IDLE:if (poll_tick && !busy)
                begin
                    address <= IMU_ADDRESS;
                    write_count <= 1;
                    write_data <= 32'h3d;
                    read_count <= 6;
                    start <= 1;
                    state <= ANGLES;
                    poll_count <= 0;
                end
                ANGLES:if (done)
                begin
                    sensor_faults[0] <= error;
                    if (!error)
                    begin
                        roll <= read_data[15:0];
                        pitch <= read_data[31:16];
                        yaw <= read_data[47:32];
                    end

                    else if (error_count != 65535)error_count <= error_count + 1;
                    address <= IMU_ADDRESS;
                    write_count <= 1;
                    write_data <= 32'h51;
                    read_count <= 8;
                    start <= 1;
                    state <= QUAT;
                end
                QUAT:if (done)
                begin
                    sensor_faults[0] <= error;
                    sensor_faults[3] <= !error && !(norm_q > 33'd536870912 && norm_q < 33'd1610612736);
                    if (!error && norm_q > 33'd536870912 && norm_q < 33'd1610612736)
                    begin
                        qw <= next_qw;
                        qx <= next_qx;
                        qy <= next_qy;
                        qz <= next_qz;
                        imu_seen <= 1;
                        imu_age <= 0;
                        orientation_update <= 1;
                    end

                    else if (error_count != 65535)error_count <= error_count + 1;
                    if (pressure_poll_count >= 10)
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
                STOP_PERIODIC:if (done)
                begin
                    sensor_faults[1] <= error;
                    if (error)
                    begin
                        if (error_count != 65535)error_count <= error_count + 1;
                        if (AUTO_SHT_ADDRESS) sht_selected <= sht_selected ^ 7'h01;
                        state <= IDLE;
                    end
                    else begin timer <= 0;state <= STOP_WAIT;end
                end
                STOP_WAIT:if (timer >= CLK_HZ / 1000)
                begin
                    address <= sht_selected;write_count <= 2;write_data <= 32'h6630;
                    read_count <= 0;start <= 1;state <= HEATER_OFF;
                end
                else timer <= timer + 1;
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
                TEMP_CMD:if (done)
                begin
                    sensor_faults[1] <= error;
                    if (error)
                    begin
                        if (error_count != 65535)error_count <= error_count + 1;
                        if (AUTO_SHT_ADDRESS && (sht_selected == 7'h44 || sht_selected == 7'h45)) sht_selected <=
                            sht_selected ^ 7'h01;
                        state <= IDLE;
                    end

                    else
                    begin
                        timer <= 0;
                        state <= TEMP_DELAY;
                    end
                end
                TEMP_DELAY:if (timer >= CLK_HZ / 100)
                begin
                    address <= sht_selected;
                    write_count <= 0;
                    read_count <= 6;
                    start <= 1;
                    state <= TEMP_READ;
                end

                else timer <= timer + 1;
                TEMP_READ:if (done)
                begin
                    sensor_faults[1] <= error;
                    sensor_faults[2] <= !error && (crc16word(raw_temperature) != read_data[23:16] ||
                        crc16word({read_data[31:24],
                        read_data[39:32]}) != read_data[47:40]);
                    sensor_faults[4] <= !error && (converted_temperature < -2000 || converted_temperature > 6000);
                    if (!error && crc16word(raw_temperature) == read_data[23:16] &&
                        crc16word({read_data[31:24], read_data[39:32]}) == read_data[47:40] &&
                        converted_temperature >= - 2000 && converted_temperature <= 6000)
                    begin
                        temperature_centi <= converted_temperature[15:0];
                        humidity_raw <= {read_data[31:24], read_data[39:32]};
                        temp_age <= 0;
                        temp_seen <= 1;
                    end

                    else if (error_count != 65535)error_count <= error_count + 1;
                    state <= IDLE;
                end
                default:state <= BOOT;
            endcase
        end
    end
endmodule
