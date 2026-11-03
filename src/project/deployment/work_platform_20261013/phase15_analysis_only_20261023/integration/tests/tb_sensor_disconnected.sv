`timescale 1ns/1ps
module tb_sensor_disconnected;
 reg clk=0;always #10 clk=~clk;reg rst_n=0;tri1 scl,sda;
 wire signed [15:0] t,roll,pitch,yaw,qw,qx,qy,qz;wire[15:0]rh,errors;wire[31:0]p,speed,env_seq,pose_seq;wire signed[31:0]sq;
 wire tv,pv,ov,ev;wire[1:0]mode;wire[7:0]faults;
 instrument_sensors #(.CLK_HZ(400000)) dut(.clk(clk),.rst_n(rst_n),.scl(scl),.sda(sda),.temperature_centi(t),.roll(roll),.pitch(pitch),.yaw(yaw),.qw(qw),.qx(qx),.qy(qy),.qz(qz),.humidity_raw(rh),.pressure_pa(p),.temperature_valid(tv),.pressure_valid(pv),.orientation_valid(ov),.speed_float(speed),.speed_q16(sq),.environment_mode(mode),.environment_valid(ev),.environment_sequence(env_seq),.pose_sequence(pose_seq),.sensor_faults(faults),.sensor_error_count(errors));
 initial begin repeat(4)@(negedge clk);rst_n=1;repeat(850000)@(negedge clk);
 if(tv||pv||ov||pose_seq!=0||faults==0||errors==0)$fatal(1,"disconnected sensors incorrectly valid or undiagnosed faults=%h errors=%d",faults,errors);
 if(!ev||mode!=0||sq<330*65536||sq>350*65536)$fatal(1,"safe sound speed fallback invalid speed=%h mode=%d",speed,mode);
 $display("SENSOR_DISCONNECTED_PASS noACK faults=%h errors=%d invalid_samples safe_fallback_Q16=%d",faults,errors,sq);$finish;end
endmodule
