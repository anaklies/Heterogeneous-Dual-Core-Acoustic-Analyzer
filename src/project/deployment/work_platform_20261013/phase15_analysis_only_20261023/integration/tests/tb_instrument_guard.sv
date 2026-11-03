`timescale 1ns/1ps
module tb_instrument_guard;
 reg[1023:0]host_cfg=0,active_cfg=0;reg[1:0]leases=0;wire record_arm=active_cfg[259];
 reg[31:0]error_flags=0,handoff_drops=0,lost_events=0;reg recorder_fault=0;reg[7:0]sensor_faults=0;
 wire [31:0] all_faults=error_flags|{8'b0,(|sensor_faults),(handoff_drops!=0),(lost_events!=0),recorder_fault,20'b0};
 wire [34:0] req0_end={3'b0,host_cfg[9*32+:32]}+{3'b0,host_cfg[10*32+:32]};
 wire [34:0] req1_end={3'b0,host_cfg[13*32+:32]}+{3'b0,host_cfg[10*32+:32]};
 wire [34:0] req_analysis_end={3'b0,host_cfg[2*32+:32]}+{1'b0,host_cfg[3*32+:32],2'b0};
 wire raw_legal=!(host_cfg[259]||record_arm||(|leases))||(
 host_cfg[10*32+:32]>=16777216&&(host_cfg[10*32+:32]&(host_cfg[10*32+:32]-1))==0&&
 host_cfg[9*32+:12]==0&&host_cfg[13*32+:12]==0&&
 host_cfg[9*32+:32]>=host_cfg[11*32+:32]&&host_cfg[13*32+:32]>=host_cfg[11*32+:32]&&
 req0_end<={3'b0,host_cfg[12*32+:32]}&&req1_end<={3'b0,host_cfg[12*32+:32]}&&
 (req0_end<={3'b0,host_cfg[13*32+:32]}||req1_end<={3'b0,host_cfg[9*32+:32]})&&
 (req0_end<={3'b0,host_cfg[2*32+:32]}||req_analysis_end<={3'b0,host_cfg[9*32+:32]})&&
 (req1_end<={3'b0,host_cfg[2*32+:32]}||req_analysis_end<={3'b0,host_cfg[13*32+:32]}));
 wire geometry_locked=(record_arm||(|leases))&&
 (host_cfg[9*32+:128]!=active_cfg[9*32+:128]||host_cfg[13*32+:32]!=active_cfg[13*32+:32]);

 initial begin
 host_cfg[9*32+:32]=32'h10000000;host_cfg[13*32+:32]=32'h11000000;host_cfg[10*32+:32]=32'h1000000;
 host_cfg[11*32+:32]=32'h10000000;host_cfg[12*32+:32]=32'h14000000;
 host_cfg[2*32+:32]=32'h12000000;host_cfg[3*32+:32]=32'h400000;active_cfg=host_cfg;
 leases=1;#1;if(!raw_legal||geometry_locked)$fatal(1,"nonoverlapping config rejected");
 host_cfg[2*32+:32]=32'h10000000;#1;if(raw_legal)$fatal(1,"leased bank0 overwritten while disarmed");
 leases=2;#1;if(raw_legal)$fatal(1,"protected bank ranges bypassed");
 leases=0;active_cfg[259]=1;#1;if(raw_legal)$fatal(1,"disarm config bypassed current recording");
 active_cfg[259]=0;#1;if(!raw_legal)$fatal(1,"fully released bank not reusable");
 leases=1;host_cfg[2*32+:32]=32'h12000000;host_cfg[9*32+:32]=32'h13000000;#1;if(!geometry_locked)$fatal(1,"leased geometry changed");
 error_flags=32'h80000;#1;if(all_faults!=32'h80000)$fatal(1,"background category changed");
 error_flags=0;lost_events=1;#1;if(all_faults!=32'h200000)$fatal(1,"lost event collides with background");
 lost_events=0;sensor_faults=8'hc0;#1;if(all_faults!=32'h800000)$fatal(1,"sensor collides with protocol faults");
 $display("INSTRUMENT_GUARD_PASS leased-bank exclusion disarm race fault categories");$finish;
 end
endmodule
