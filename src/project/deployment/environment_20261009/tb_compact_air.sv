`timescale 1ns/1ps
module tb_compact_air;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0,temperature_valid=0,humidity_valid=0,pressure_valid=0;
    reg signed[15:0]temperature_centi=0;reg[15:0]humidity_raw=0;reg[31:0]pressure_pa=0;
    wire busy,done;wire signed[19:0]temperature_correction_q16;wire[1:0]environment_mode;
    reg[95:0]v[0:199];integer ticks=0,begin_tick,max_ticks=0;
    air_speed_correction #(.COEFF_FILE("air_delta_coeff.mem")) dut(.*);
    always @(posedge clk)ticks<=ticks+1;
    initial
    begin
        $readmemh("compact_vectors.mem",v);repeat(4)@(negedge clk);rst_n=1;
        for(integer i=0;i<200;i=i+1)
        begin
            {pressure_valid,humidity_valid,temperature_valid,pressure_pa,humidity_raw,temperature_centi}=v[i][66:0];
            begin_tick=ticks;start=1;@(negedge clk);start=0;temperature_centi=-2000;humidity_raw=0;pressure_pa=0;
            wait(done);@(negedge clk);
            if(temperature_correction_q16!==v[i][86:67] || environment_mode!==v[i][88:87])$fatal(1,"compact air case %0d delta=%0d expected=%0d mode=%0d",i,temperature_correction_q16,$signed(v[i][86:67]),environment_mode);
            if(ticks-begin_tick>max_ticks)max_ticks=ticks-begin_tick;
        end
        $display("PASS 200 compact air snapshots, max %0d cycles",max_ticks);$finish;
    end
    initial begin #1000000;$fatal(1,"compact air timeout");end
endmodule
