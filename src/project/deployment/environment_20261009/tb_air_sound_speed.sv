`timescale 1ns/1ps
module tb_air_sound_speed;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0;
    reg signed [15:0] temperature_centi=0;
    reg temperature_valid=0,humidity_valid=0,pressure_valid=0;
    reg [15:0] humidity_raw=0;
    reg [31:0] pressure_pa=0;
    wire busy,done;wire [31:0] sound_speed_float;
    wire signed [31:0] sound_speed_q16;wire [1:0] environment_mode;
    wire signed [31:0] effective_temperature_q16;
    reg [135:0] vectors[0:199];integer cycles=0,max_cycles=0,begins_at;
    air_sound_speed #(.COEFF_FILE("air_coeff.mem")) dut(.*);
    always @(posedge clk)cycles<=cycles+1;
    initial
    begin
        $readmemh("air_vectors.mem",vectors);
        repeat(4)@(negedge clk);rst_n=1;
        for(integer i=0;i<200;i=i+1)
        begin
            {pressure_valid,humidity_valid,temperature_valid,pressure_pa,humidity_raw,temperature_centi}=vectors[i][66:0];
            begins_at=cycles;start=1;@(negedge clk);start=0;
            // Mid-computation sensor changes must not tear the snapshot.
            temperature_centi=-2000;humidity_raw=0;pressure_pa=0;
            wait(done);@(negedge clk);
            if(sound_speed_q16!==vectors[i][98:67] || sound_speed_float!==vectors[i][130:99] || environment_mode!==vectors[i][132:131])
                $fatal(1,"air case %0d Q16=%0d expected=%0d float=%h expected=%h mode=%0d",i,sound_speed_q16,vectors[i][98:67],sound_speed_float,vectors[i][130:99],environment_mode);
            if(cycles-begins_at>max_cycles)max_cycles=cycles-begins_at;
        end
        $display("PASS 200 air compensation snapshots/fallbacks; maximum latency %0d cycles",max_cycles);$finish;
    end
    initial begin #2000000;$fatal(1,"air compensation deadlock");end
endmodule
