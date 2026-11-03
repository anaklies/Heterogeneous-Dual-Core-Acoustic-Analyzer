`timescale 1ns/1ps
// Cramer-based bounded approximation; CO2 assumed 425 ppm.
// One shared multiplier/divider and 96x32 coefficient ROM. No PS arithmetic.
module air_sound_speed #(
    parameter COEFF_FILE = "pl/coeff/air_coeff.mem"
)
(
    input wire clk, rst_n, start,
    input wire signed [15:0] temperature_centi,
    input wire temperature_valid,
    input wire [15:0] humidity_raw,
    input wire humidity_valid,
    input wire [31:0] pressure_pa,
    input wire pressure_valid,
    output reg busy, done,
    output reg [31:0] sound_speed_float,
    output reg signed [31:0] sound_speed_q16,
    output reg signed [31:0] effective_temperature_q16,
    output reg [1:0] environment_mode
);
    localparam IDLE=0, BASE_MUL=1, DIVIDE=2, BASE_DONE=3, TEMP_DONE=4,
        READ_ROM=5, WAIT_ROM=6, DRY_SETUP=7, DRY_MUL=8, DRY_DONE=9,
        HUM_SETUP=10, HUM_MUL=11, HUM_DONE=12, RAW_SETUP=13, RAW_MUL=14,
        RAW_DONE=15, PRESS_SETUP=16, PRESS_MUL=17, PRESS_DONE=18,
        DRIFT_SETUP=19, DRIFT_MUL=20, COMPLETE=21, EFFECTIVE_DONE=22;
    reg [4:0] state, return_state;
    reg signed [15:0] temp;
    reg [15:0] rh;
    reg [16:0] pressure;
    reg [1:0] mode;
    reg [39:0] dividend;
    reg [23:0] quotient;
    reg [17:0] remainder;
    reg [16:0] divisor;
    reg [5:0] bits_left;
    reg negative;
    reg signed [23:0] mul_a;
    reg signed [17:0] mul_b;
    wire signed [41:0] product = mul_a * mul_b;
    wire [41:0] abs_product = product[41] ? -product : product;
    wire [18:0] trial = {remainder, dividend[39]};
    wire [23:0] next_quotient = {quotient[22:0], trial >= divisor};
    reg signed [31:0] base_q16, dry_correction, wet_coefficient, wet_normal,
        wet_correction, drift_correction;
    reg [4:0] temp_index;
    reg [6:0] fraction;
    reg [2:0] phase;
    reg signed [23:0] dry_lo, hum_lo, dp_lo, dry_hi, hum_hi;
    (* rom_style="block" *) reg signed [31:0] coefficients[0:95];
    reg signed [31:0] rom_q;
    wire [4:0] upper_index = temp_index == 30 ? 30 : temp_index + 1;
    wire [6:0] rom_address = phase < 3 ? temp_index*3+phase : upper_index*3+(phase-3);
    wire signed [31:0] total_q16 = base_q16 + dry_correction + wet_correction + drift_correction;
    wire temp_ok = temperature_valid && temperature_centi >= -2000 && temperature_centi <= 6000;
    wire humid_ok = temp_ok && temperature_centi >= 0 && temperature_centi <= 3000 && humidity_valid;
    wire press_ok = pressure_valid && pressure_pa >= 75000 && pressure_pa <= 102000;
    wire signed [15:0] selected_temp = temp_ok ? temperature_centi : 16'sd1930;
    wire [15:0] abs_temp = selected_temp < 0 ? -selected_temp : selected_temp;
    initial $readmemh(COEFF_FILE, coefficients);
    always @(posedge clk) if (state == READ_ROM) rom_q <= coefficients[rom_address];
    task automatic divide(input [39:0] value, input [16:0] denominator, input [4:0] destination);
        begin
            dividend <= value; divisor <= denominator; quotient <= 0;
            remainder <= 0; bits_left <= 40; return_state <= destination; state <= DIVIDE;
        end
    endtask
    always @(posedge clk)
    begin
        if (!rst_n)
        begin
            busy<=0;done<=0;state<=IDLE;environment_mode<=0;
            sound_speed_q16<=32'sd22478574;sound_speed_float<=32'h43ab7f76;
            effective_temperature_q16<=32'sd1264844;
            temp<=1930;rh<=0;pressure<=101325;mode<=0;
            dividend<=0;divisor<=100;quotient<=0;remainder<=0;bits_left<=0;
            return_state<=IDLE;negative<=0;mul_a<=0;mul_b<=0;
            base_q16<=0;dry_correction<=0;wet_coefficient<=0;wet_normal<=0;
            wet_correction<=0;drift_correction<=0;
            temp_index<=0;fraction<=0;phase<=0;
            dry_lo<=0;hum_lo<=0;dp_lo<=0;dry_hi<=0;hum_hi<=0;
        end
        else
        begin
            done<=0;
            case (state)
                IDLE: if (start)
                begin
                    busy<=1;temp<=selected_temp;rh<=humidity_raw;
                    pressure<=press_ok ? pressure_pa[16:0] : 17'd101325;
                    mode<=!temp_ok ? 0 : (!humid_ok ? 1 : (press_ok ? 3 : 2));
                    dry_correction<=0;wet_correction<=0;drift_correction<=0;
                    mul_a<=$signed({8'b0,abs_temp});mul_b<=18'sd39715;
                    negative<=selected_temp[15];state<=BASE_MUL;
                end
                BASE_MUL: divide(abs_product[33:0],17'd100,BASE_DONE);
                DIVIDE:
                begin
                    dividend<=dividend<<1;quotient<=next_quotient;
                    remainder<=trial>=divisor ? trial-divisor : trial;
                    bits_left<=bits_left-1;
                    if (bits_left==1)state<=return_state;
                end
                BASE_DONE:
                begin
                    base_q16<=32'sd21712077+(negative ? -$signed({8'b0,quotient}) : $signed({8'b0,quotient}));
                    if (mode>=2)divide({18'b0,temp},17'd100,TEMP_DONE);
                    else state<=COMPLETE;
                end
                TEMP_DONE:
                begin
                    temp_index<=quotient[4:0];fraction<=remainder[6:0];phase<=0;state<=READ_ROM;
                end
                READ_ROM: state<=WAIT_ROM;
                WAIT_ROM:
                begin
                    case (phase)
                        0:dry_lo<=rom_q[23:0];1:hum_lo<=rom_q[23:0];2:dp_lo<=rom_q[23:0];
                        3:dry_hi<=rom_q[23:0];4:hum_hi<=rom_q[23:0];
                    endcase
                    if (phase==4)state<=DRY_SETUP;
                    else begin phase<=phase+1;state<=READ_ROM;end
                end
                DRY_SETUP:
                begin
                    mul_a<=dry_hi-dry_lo;mul_b<=$signed({11'b0,fraction});
                    negative<=dry_hi<dry_lo;state<=DRY_MUL;
                end
                DRY_MUL: divide(abs_product[33:0],17'd100,DRY_DONE);
                DRY_DONE:
                begin
                    dry_correction<=$signed(dry_lo)+(negative ? -$signed({8'b0,quotient}) : $signed({8'b0,quotient}));
                    state<=HUM_SETUP;
                end
                HUM_SETUP:
                begin
                    mul_a<=hum_hi-hum_lo;mul_b<=$signed({11'b0,fraction});state<=HUM_MUL;
                end
                HUM_MUL: divide(abs_product[33:0],17'd100,HUM_DONE);
                HUM_DONE: begin wet_coefficient<=$signed(hum_lo)+$signed({8'b0,quotient});state<=RAW_SETUP;end
                RAW_SETUP: begin mul_a<=wet_coefficient[23:0];mul_b<=$signed({2'b0,rh});state<=RAW_MUL;end
                RAW_MUL: divide(abs_product[33:0],17'd65535,RAW_DONE);
                RAW_DONE: begin wet_normal<=$signed({8'b0,quotient});state<=PRESS_SETUP;end
                PRESS_SETUP: begin mul_a<=wet_normal[23:0];mul_b<=18'sd101325;state<=PRESS_MUL;end
                PRESS_MUL: divide(abs_product[33:0],pressure,PRESS_DONE);
                PRESS_DONE: begin wet_correction<=$signed({8'b0,quotient});state<=DRIFT_SETUP;end
                DRIFT_SETUP:
                begin
                    mul_a<=$signed({7'b0,pressure})-24'sd101325;mul_b<=dp_lo[17:0];state<=DRIFT_MUL;
                end
                DRIFT_MUL: begin drift_correction<=product>>>8;state<=COMPLETE;end
                COMPLETE:
                begin
                    sound_speed_q16<=total_q16;
                    // Every bounded result lies in [256,512); Q16 to float.
                    sound_speed_float<={1'b0,8'd135,total_q16[23:1]};
                    environment_mode<=mode;
                    // Encode speed for the unchanged legacy linear-c kernel.
                    // Physical SHT30 temperature telemetry is kept separate.
                    negative<=total_q16<32'sd21712077;
                    if(total_q16<32'sd21712077)
                        divide((40'(32'sd21712077-total_q16))<<16,17'd39715,EFFECTIVE_DONE);
                    else divide((40'(total_q16-32'sd21712077))<<16,17'd39715,EFFECTIVE_DONE);
                end
                EFFECTIVE_DONE:
                begin
                    effective_temperature_q16<=negative ? -$signed({8'b0,quotient}) : $signed({8'b0,quotient});
                    busy<=0;done<=1;state<=IDLE;
                end
                default: begin state<=IDLE;busy<=0;end
            endcase
        end
    end
endmodule
