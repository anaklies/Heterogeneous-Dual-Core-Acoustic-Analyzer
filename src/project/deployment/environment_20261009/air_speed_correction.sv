`timescale 1ns/1ps
// Shared serial arithmetic computes a temperature-equivalent correction.
// The existing config writer supplies the physical T/100 conversion.
module air_speed_correction #(parameter COEFF_FILE="pl/coeff/air_delta_coeff.mem")
(
    input wire clk,rst_n,start,
    input wire signed [15:0] temperature_centi,
    input wire temperature_valid,
    input wire [15:0] humidity_raw,
    input wire humidity_valid,
    input wire [31:0] pressure_pa,
    input wire pressure_valid,
    output reg busy,done,
    output reg signed [19:0] temperature_correction_q16,
    output reg [1:0] environment_mode
);
    localparam IDLE=0,INDEX_MUL=1,READ=2,WAIT_ROM=3,DRY_SETUP=4,DRY_MUL=5,
        DRY_DONE=6,HUM_SETUP=7,HUM_MUL=8,HUM_DONE=9,RAW_SETUP=10,RAW_MUL=11,
        RAW_DONE=12,PRESS_SETUP=13,PRESS_MUL=14,PRESS_DONE=15,DRIFT_SETUP=16,
        DRIFT_MUL=17,CORRECT=18,DIVIDE=19,COMPLETE=20;
    reg [4:0] state,return_state;
    reg [11:0] tc;reg [15:0] rh;reg [16:0] pressure;
    reg [4:0] index;reg [6:0] fraction;reg [2:0] phase;
    reg signed [15:0] dlo,hlo,dp,dhi,hhi,dry,wet_coefficient,wet_normal,wet,drift;
    (* rom_style="block" *)reg signed [15:0] coefficients[0:95];
    reg signed [15:0] rom_q;
    reg signed [15:0] mul_a;reg signed [17:0] mul_b;
    (* use_dsp="yes" *)wire signed [33:0] product=mul_a*mul_b;
    wire [33:0] abs_product=product[33] ? -product : product;
    reg [34:0] dividend;reg [16:0] divisor;reg [17:0] remainder;
    reg [19:0] quotient;reg [5:0] bits;reg negative;
    wire [18:0] trial={remainder,dividend[34]};
    (* use_dsp="yes" *) wire signed [19:0] division_difference=$signed({1'b0,trial})-$signed({3'b0,divisor});
    wire division_accept=!division_difference[19];
    wire [19:0] next_quotient={quotient[18:0],division_accept};
    wire [4:0] upper=index==30 ? 30 : index+1;
    wire [6:0] address=phase<3 ? index*3+phase : upper*3+(phase-3);
    wire signed [15:0] correction=dry+wet+drift;
    wire tok=temperature_valid && temperature_centi>=-2000 && temperature_centi<=6000;
    wire hok=tok && temperature_centi>=0 && temperature_centi<=3000 && humidity_valid;
    wire pok=pressure_valid && pressure_pa>=75000 && pressure_pa<=102000;
    initial $readmemh(COEFF_FILE,coefficients);
    always @(posedge clk)if(state==READ)rom_q<=coefficients[address];
    task automatic divide(input [34:0] numerator,input [16:0] denominator,input [4:0] next);
        begin dividend<=numerator;divisor<=denominator;quotient<=0;remainder<=0;bits<=35;return_state<=next;state<=DIVIDE;end
    endtask
    always @(posedge clk)
    begin
        if(!rst_n)
        begin
            state<=IDLE;busy<=0;done<=0;temperature_correction_q16<=0;environment_mode<=0;
            tc<=0;rh<=0;pressure<=101325;index<=0;fraction<=0;phase<=0;
            dlo<=0;hlo<=0;dp<=0;dhi<=0;hhi<=0;dry<=0;wet_coefficient<=0;wet_normal<=0;wet<=0;drift<=0;
            mul_a<=0;mul_b<=0;dividend<=0;divisor<=100;remainder<=0;quotient<=0;bits<=0;negative<=0;return_state<=IDLE;
        end
        else
        begin
            done<=0;
            case(state)
                IDLE:if(start)
                begin
                    busy<=1;tc<=temperature_centi[11:0];rh<=humidity_raw;pressure<=pok?pressure_pa[16:0]:17'd101325;
                    environment_mode<=!tok?0:(!hok?1:(pok?3:2));
                    if(hok)
                    begin mul_a<=$signed({4'b0,temperature_centi[11:0]});mul_b<=18'sd41944;state<=INDEX_MUL;end
                    else begin temperature_correction_q16<=0;busy<=0;done<=1;end
                end
                INDEX_MUL:
                begin
                    // Exact floor(T_centi/100) on 0..3000, exhaustively checked.
                    index<=product[26:22];fraction<=tc-100*product[26:22];phase<=0;state<=READ;
                end
                READ:state<=WAIT_ROM;
                WAIT_ROM:
                begin
                    case(phase)0:dlo<=rom_q;1:hlo<=rom_q;2:dp<=rom_q;3:dhi<=rom_q;4:hhi<=rom_q;endcase
                    if(phase==4)state<=DRY_SETUP;else begin phase<=phase+1;state<=READ;end
                end
                DRY_SETUP:begin mul_a<=dhi-dlo;mul_b<=$signed({11'b0,fraction});negative<=dhi<dlo;state<=DRY_MUL;end
                DRY_MUL:divide({1'b0,abs_product},100,DRY_DONE);
                DRY_DONE:begin dry<=dlo+(negative?-$signed(quotient):$signed(quotient));state<=HUM_SETUP;end
                HUM_SETUP:begin mul_a<=hhi-hlo;mul_b<=$signed({11'b0,fraction});state<=HUM_MUL;end
                HUM_MUL:divide({1'b0,abs_product},100,HUM_DONE);
                HUM_DONE:begin wet_coefficient<=hlo+quotient;state<=RAW_SETUP;end
                RAW_SETUP:begin mul_a<=wet_coefficient;mul_b<=$signed({2'b0,rh});state<=RAW_MUL;end
                RAW_MUL:divide({1'b0,abs_product},65535,RAW_DONE);
                RAW_DONE:begin wet_normal<=quotient;state<=PRESS_SETUP;end
                PRESS_SETUP:begin mul_a<=wet_normal;mul_b<=18'sd101325;state<=PRESS_MUL;end
                PRESS_MUL:divide({1'b0,abs_product},pressure,PRESS_DONE);
                PRESS_DONE:begin wet<=quotient;state<=DRIFT_SETUP;end
                DRIFT_SETUP:begin mul_a<=$signed({1'b0,pressure})-18'sd101325;mul_b<={{2{dp[15]}},dp};state<=DRIFT_MUL;end
                DRIFT_MUL:begin drift<=product>>>12;state<=CORRECT;end
                CORRECT:
                begin
                    negative<=correction[15];
                    if(correction[15])divide((35'(-correction))<<20,39715,COMPLETE);
                    else divide((35'(correction))<<20,39715,COMPLETE);
                end
                DIVIDE:
                begin
                    dividend<=dividend<<1;quotient<=next_quotient;remainder<=division_accept?division_difference[17:0]:trial;bits<=bits-1;
                    if(bits==1)state<=return_state;
                end
                COMPLETE:begin temperature_correction_q16<=negative?-$signed(quotient):$signed(quotient);busy<=0;done<=1;state<=IDLE;end
                default:begin state<=IDLE;busy<=0;end
            endcase
        end
    end
endmodule
