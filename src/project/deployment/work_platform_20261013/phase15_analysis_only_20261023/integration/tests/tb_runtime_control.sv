`timescale 1ns/1ps
module tb_runtime_control;
 reg clk=0;always #5 clk=~clk;reg rst_n=0;
 reg [11:0] aa=0,ar=0;reg av=0,wv=0,br=1,arv=0,rr=1;reg [31:0] wd=0;reg [3:0] ws=15;
 wire awr,wr,bv,arr,rv;wire [1:0] bp,rp;wire [31:0] rd;wire cv;reg cr=0,ca=0,cj=0,publish=0;
 wire [511:0] payload;reg [1023:0] words=0;
 runtime_control dut(.clk(clk),.rst_n(rst_n),.awaddr(aa),.awvalid(av),.awready(awr),.wdata(wd),.wstrb(ws),.wvalid(wv),.wready(wr),.bresp(bp),.bvalid(bv),.bready(br),.araddr(ar),.arvalid(arv),.arready(arr),.rdata(rd),.rresp(rp),.rvalid(rv),.rready(rr),.cfg_valid(cv),.cfg_ready(cr),.cfg_applied(ca),.cfg_rejected(cj),.cfg_payload(payload),.result_valid(publish),.result_words(words),.live_faults(32'b0),.active_config(32'd7),.irq());
 task put(input[11:0] a,input[31:0] d,input[1:0] expect_resp);
 begin @(negedge clk);aa=a;av=1;while(!awr)@(negedge clk);@(negedge clk);av=0;
 repeat(2)@(negedge clk);wd=d;wv=1;while(!wr)@(negedge clk);@(negedge clk);wv=0;
 while(!bv)@(negedge clk);if(bp!=expect_resp)$fatal(1,"BRESP mismatch");@(negedge clk);end endtask
 task get(input[11:0] a,input[31:0] expected);
 begin @(negedge clk);ar=a;arv=1;while(!arr)@(negedge clk);@(negedge clk);arv=0;
 while(!rv)@(negedge clk);if(rp||rd!==expected)$fatal(1,"read%h got%h expected%h",a,rd,expected);@(negedge clk);end endtask
 initial begin
 repeat(3)@(negedge clk);rst_n=1;get(0,32'h534d4132);get(4,2);get(12,0);
 put('h40,123,0);put('h44,7,0);put('h20,1,0);if(!cv||payload[31:0]!=123)$fatal(1,"commit failed");
 put('h40,456,0);if(payload[31:0]!=123)$fatal(1,"live shadow leaked into request");put('h20,1,2);
 cr=1;@(negedge clk);cr=0;ca=1;@(negedge clk);ca=0;
 words[31:0]=987;publish=1;@(negedge clk);publish=0;get('h18,1);get('h100,987);
 put('h40,32'hdeadbeef,0);ws=1;put('h40,32'h12,0);ws=15;get('h40,32'hdeadbe12);
 put('h20,1,0);
 fork
  begin put('h24,2,0);end
  begin wait(dut.ap&&dut.wp);@(negedge clk);ca=1;@(negedge clk);ca=0;end
 join
 get('h20,6);
 $display("RUNTIME_CONTROL_PASS independent_AW_W atomic_config epoch_snapshot byte_write busy_reject");$finish;
 end
 initial begin #20000;$fatal(1,"timeout");end
endmodule
