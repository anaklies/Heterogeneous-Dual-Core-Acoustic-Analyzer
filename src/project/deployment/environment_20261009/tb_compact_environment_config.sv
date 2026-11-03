`timescale 1ns/1ps
module tb_compact_environment_config;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0,temperature_valid=0,humidity_valid=0,pressure_valid=0;
    reg signed[15:0]temperature_centi=0;reg[15:0]humidity_raw=0;reg[31:0]pressure_pa=0;
    wire air_busy,air_done;wire signed[19:0]temperature_correction_q16;wire[1:0]environment_mode;
    reg rotation_valid=1;reg[287:0]rotation_q16={32'd65536,32'd0,32'd0,32'd0,32'd65536,32'd0,32'd0,32'd0,32'd65536};
    reg[7:0]observations=20,background_observations=20;reg background_enabled=0;
    reg[31:0]background_ratio_float=0,dt_float=32'h3e800000;wire busy,done,world_frame_valid,temp_compensated,write_valid;
    reg write_ready=1;wire[3:0]write_address;wire[31:0]write_float;
    reg[95:0]v[0:199];integer count=0,ticks=0,fd;reg[31:0]config_temp;
    air_speed_correction #(.COEFF_FILE("air_delta_coeff.mem")) air(.busy(air_busy),.done(air_done),.*);
    sensor_config_writer #(.HAS_AIR_SOUND_SPEED(1)) cfg(.sound_speed_valid(air_done),.*);
    always @(posedge clk)
    begin
        ticks<=ticks+1;
        if(write_valid && write_ready)
        begin
            if(write_address==0)config_temp<=write_float;
            if(write_address==14 && write_float!=0)$fatal(1,"unused legacy slot changed");
            count<=count+1;
        end
    end
    always @(negedge clk)write_ready=ticks%7!=0;
    initial
    begin
        fd=$fopen("config_environment_vectors.csv","w");$fwrite(fd,"case,temp_centi,rh_raw,pressure_pa,flags,mode,config0\n");
        $readmemh("compact_vectors.mem",v);repeat(4)@(negedge clk);rst_n=1;
        for(integer i=0;i<200;i=i+1)
        begin
            {pressure_valid,humidity_valid,temperature_valid,pressure_pa,humidity_raw,temperature_centi}=v[i][66:0];
            count=0;start=1;@(negedge clk);start=0;
            temperature_centi=-2000;humidity_raw=0;pressure_pa=0;temperature_valid=0;
            wait(done);@(negedge clk);
            if(count!=16)$fatal(1,"configuration epoch incomplete %0d",count);
            $fwrite(fd,"%0d,%0d,%0d,%0d,%0d,%0d,%08h\n",i,$signed(v[i][15:0]),v[i][31:16],v[i][63:32],v[i][66:64],environment_mode,config_temp);
        end
        $fclose(fd);$display("PASS 200 actual config epochs, atomic sensor/pose, early/late correction completion and output backpressure");$finish;
    end
    initial begin #1500000;$fatal(1,"compact config deadlock");end
endmodule
