`timescale 1ns/1ps
module tb_event_power_detector;
 logic clk=0;always #5 clk=~clk;
 logic rst_n=0,cfg_commit=0,in_valid=0,feature_valid=1,in_ready,out_valid,out_ready=1;
 logic [191:0] cfg_data=0,channel_power=0;
 logic [255:0] band_power=0;
 logic [63:0] sample_timestamp=0,out_timestamp;
 logic [31:0] config_generation,out_config_generation;
 logic [7:0] out_reason,out_band_mask,sticky_fault;
 logic out_started,out_ended,out_active,learned;
 logic [34:0] background_power;
 logic [255:0] background_bands;
 integer checks=0, starts=0;
 logic [63:0] next_ts=0;
 event_power_detector dut(.*);
 task automatic check(input bit ok,input string msg);
   checks=checks+1;
   if(!ok) $fatal(1,"CHECK %0d FAILED: %s",checks,msg);
 endtask
 task automatic commit;
   @(negedge clk);cfg_commit=1;
   @(posedge clk);#1;
   @(negedge clk);cfg_commit=0;
 endtask
 task automatic frame(input integer p,input integer band0,input integer band1);
   @(negedge clk);
   while(!in_ready) @(negedge clk);
   for(integer c=0;c<6;c=c+1) channel_power[c*32+:32]=p;
   band_power=0;band_power[31:0]=band0;band_power[63:32]=band1;
   sample_timestamp=next_ts;next_ts=next_ts+1024;in_valid=1;
   @(posedge clk);#1;
   if(out_valid && out_started) starts=starts+1;
   @(negedge clk);in_valid=0;
 endtask
 initial begin
   repeat(3) @(negedge clk);rst_n=1;
   cfg_data[3:0]=7; // enabled, relearn, locked
   cfg_data[15:8]=8'hff;cfg_data[31:16]=1024;cfg_data[47:32]=768;
   cfg_data[63:48]=64;cfg_data[79:64]=3;cfg_data[95:80]=2;
   cfg_data[111:96]=4;cfg_data[127:112]=2;cfg_data[159:128]=1;
   cfg_data[163:160]=2;cfg_data[191:176]=1024;commit();
   frame(100,100,10);check(!learned && !out_started,"warm-up block 1");
   frame(100,100,10);frame(100,100,10);check(learned,"three-block learning");
   repeat(6) begin frame(100,100,10);check(!out_started,"regular background quiet");end
   frame(500,500,10);check(out_started && out_reason[0],"energy rise start");
   frame(100,100,10);check(out_active,"release merge pending");
   frame(500,500,10);check(!out_started && out_active,"merge before release");
   frame(500,500,10);check(out_ended && !out_active,"max length at four blocks");
   check(background_power==600 && background_bands[31:0]==100,"locked background survives max duration");
   frame(100,100,10);frame(100,100,10);
   frame(100,10,100);check(out_started && !out_reason[0] && out_reason[1] && out_band_mask==2,"equal total power spectral change");
   frame(100,100,10);frame(100,100,10);check(out_ended,"release count");
   frame(100,100,10);frame(100,100,10);
   frame(0,0,0);check(out_started && out_reason[2],"interruption/drop");
   repeat(3) frame(0,0,0);
   check(out_ended && background_power==600,"persistent loss bounded and reference preserved");
   cfg_data[1]=0;cfg_data[0]=0;commit();
   repeat(5) begin frame(500,500,100);check(!out_started && !out_active,"disabled");end
   cfg_data[0]=1;cfg_data[15:8]=1;commit();
   frame(100,10,100);check(!out_started && out_band_mask==0,"frequency selection masks excluded band");
   // Hold one valid summary for three clocks; entire payload must remain stable.
   out_ready=0;
   repeat(3) begin
     @(posedge clk);#1;check(out_valid && !in_ready && out_timestamp==next_ts-1024 && !out_started,"output stall stability");
   end
   cfg_data[15:8]=8'hff;commit();
   check(out_valid && out_config_generation+1==config_generation && out_timestamp==next_ts-1024,
     "pending result keeps old config generation on commit");
   @(negedge clk);out_ready=1;
   feature_valid=0;frame(100,100,10);check(sticky_fault[1] && !out_valid,"invalid features rejected");feature_valid=1;
   // Invalid block left a hole; next forward marker is rejected for discontinuity.
   frame(100,100,10);check(sticky_fault[3] && !out_valid,"forward gap rejected");
   frame(100,100,10);check(out_valid && !out_started,"recovery after forward gap");
   next_ts=next_ts-1024;frame(500,500,10);check(sticky_fault[2] && !out_valid,"duplicate timestamp rejected");
   // Invalid config does not replace active settings or reset locked reference.
   cfg_data[31:16]=256;commit();check(sticky_fault[0] && background_power==600,"bad atomic config rejected");
   frame(100,100,10);check(out_valid,"old config retained");
   check(starts==3,"exactly energy/band/drop event starts");
   // Explicit relearn can replace a locked reference.
   cfg_data[31:16]=1024;cfg_data[1]=1;commit();
   repeat(3) frame(200,200,20);
   check(learned && background_power==1200,"explicit relearn while locked");
   // Unlock + adaptation changes a quiet reference by the documented IIR.
   cfg_data[1]=0;cfg_data[2]=0;cfg_data[3]=1;commit();
   frame(220,220,20);check(background_power==1230,"optional adaptation");
   $display("PASS event_power_detector checks=%0d starts=%0d sticky_fault=%02x",checks,starts,sticky_fault);
   $finish;
 end
 initial begin #100000; $fatal(1,"test timeout");end
endmodule
