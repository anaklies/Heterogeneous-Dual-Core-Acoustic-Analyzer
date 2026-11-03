`timescale 1ns/1ps
// Existing physical I2C drivers and air model; no sensor arithmetic on PS.
module instrument_sensors #(parameter CLK_HZ=50000000)(
 input wire clk,rst_n,inout wire scl,sda,
 output wire signed [15:0] temperature_centi,roll,pitch,yaw,qw,qx,qy,qz,
 output wire [15:0] humidity_raw,output wire [31:0] pressure_pa,
 output wire temperature_valid,pressure_valid,orientation_valid,
 output wire [31:0] speed_float,output wire signed [31:0] speed_q16,
 output wire [1:0] environment_mode,output reg environment_valid,
 output reg [31:0] environment_sequence,pose_sequence,
 output wire [7:0] sensor_faults,output wire [15:0] sensor_error_count
);
 wire pose_update,busy,done;reg [31:0] counter;reg start;
 wire signed [31:0] effective_temperature;
 sensor_i2c_hub #(.CLK_HZ(CLK_HZ)) hub(.clk(clk),.rst_n(rst_n),.scl(scl),.sda(sda),
 .temperature_centi(temperature_centi),.temperature_valid(temperature_valid),.humidity_raw(humidity_raw),.pressure_pa(pressure_pa),.pressure_valid(pressure_valid),
 .orientation_valid(orientation_valid),.orientation_update(pose_update),.qw(qw),.qx(qx),.qy(qy),.qz(qz),.roll(roll),.pitch(pitch),.yaw(yaw),.sensor_faults(sensor_faults),.error_count(sensor_error_count));
 air_sound_speed #(.COEFF_FILE("air_coeff.mem")) air(.clk(clk),.rst_n(rst_n),.start(start),.busy(busy),.done(done),
 .temperature_centi(temperature_centi),.temperature_valid(temperature_valid),.humidity_raw(humidity_raw),.humidity_valid(temperature_valid),
 .pressure_pa(pressure_pa),.pressure_valid(pressure_valid),.sound_speed_float(speed_float),.sound_speed_q16(speed_q16),.effective_temperature_q16(effective_temperature),.environment_mode(environment_mode));
 always @(posedge clk)begin
  if(!rst_n)begin counter<=0;start<=0;environment_valid<=0;environment_sequence<=0;pose_sequence<=0;end
  else begin
   start<=0;
   if(counter>=CLK_HZ-1)begin counter<=0;if(!busy)start<=1;end else counter<=counter+1;
   if(done)begin environment_valid<=1;environment_sequence<=environment_sequence+1;end
   if(pose_update)pose_sequence<=pose_sequence+1;
  end
 end
endmodule
