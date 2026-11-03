`timescale 1ns/1ps
module tb_event_recorder;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,en=0,ev=0,ack=0,release_v=0;reg [63:0] ts=0,last=0;reg [31:0] count=0,offset=0,drops=0;
 wire we,cv,dv,bank,inc,fault;wire [31:0] base,bytes,id,frames,at,lost,gaps;wire [63:0] first,dl;wire [1:0] lease;
 event_recorder #(.PRE(2),.POST(3),.MAX_SAMPLES(128)) dut(.clk(clk),.rst_n(rst_n),.enable(en),.sample_valid(1'b0),.event_start(ev),.event_sample(ts),.last_committed(last),.committed(count),.next_offset(offset),.writer_drops(drops),.bank0_base(32'h1000),.bank1_base(32'h2000),.bank_bytes(32'd4096),.reserved_low(32'h1000),.reserved_high(32'h3000),.writer_enable(we),.writer_cfg_valid(cv),.writer_cfg_ready(1'b1),.writer_cfg_accepted(ack),.writer_cfg_base(base),.writer_cfg_bytes(bytes),.release_valid(release_v),.release_bank(1'b0),.release_id(32'd0),.descriptor_valid(dv),.descriptor_ready(1'b0),.descriptor_bank(bank),.descriptor_id(id),.descriptor_start_offset(at),.descriptor_frames(frames),.descriptor_first(first),.descriptor_last(dl),.descriptor_incomplete(inc),.leased(lease),.lost_events(lost),.handoff_drops(gaps),.fault(fault));
 initial begin
 repeat(3)@(negedge clk);rst_n=1;en=1;@(negedge clk);ack=1;@(negedge clk);ack=0;
 if(!we||fault)$fatal(1,"initial config failed");last=100;count=101;offset=3232;ts=100;ev=1;@(negedge clk);ev=0;
 last=103;count=104;offset=3328;repeat(2)@(negedge clk);
 if(we||!cv||base!='h2000||dv)$fatal(1,"writer not safely paused before sealing");
 last=105;count=106;offset=3392; // queued tail must not extend logical clip
 ack=1;@(negedge clk);ack=0;@(negedge clk);
 if(!dv||bank||id!=0||frames!=6||first!=98||dl!=103||at!=3136||!lease[0]||inc)$fatal(1,"bad retention descriptor");
 // The sealed bank cannot be released by descriptor notification alone.
 repeat(3)@(negedge clk);if(!lease[0])$fatal(1,"pinned clip lost");
 release_v=1;@(negedge clk);release_v=0;@(negedge clk);if(lease[0])$fatal(1,"release failed");
 rst_n=0;en=0;@(negedge clk);rst_n=1;en=1;@(negedge clk);ack=1;@(negedge clk);ack=0;
 drops=1;ts=100;last=100;count=101;offset=3232;ev=1;@(negedge clk);ev=0;
 last=103;count=104;offset=3328;repeat(2)@(negedge clk);ack=1;@(negedge clk);ack=0;@(negedge clk);
 if(!dv||!inc)$fatal(1,"pre-trigger gap was silently declared complete");
 rst_n=0;en=0;drops=0;@(negedge clk);rst_n=1;en=1;@(negedge clk);ack=1;@(negedge clk);ack=0;
 ts=100;last=100;count=101;offset=3232;ev=1;@(negedge clk);ev=0;
 ts=222;last=222;count=223;offset=3040;ev=1;@(negedge clk);ev=0;
 last=225;count=226;offset=3136;repeat(2)@(negedge clk);
 last=227;count=228;offset=3200;ack=1;@(negedge clk);ack=0;@(negedge clk);
 if(!dv||!inc||frames!=126||first!=100||dl!=225)$fatal(1,"wrapped capacity/drain tail misreported");
 $display("EVENT_RECORDER_PASS prepost bank_switch drained_seal lease token");$finish;
 end
 initial begin #10000;$fatal(1,"timeout");end
endmodule
