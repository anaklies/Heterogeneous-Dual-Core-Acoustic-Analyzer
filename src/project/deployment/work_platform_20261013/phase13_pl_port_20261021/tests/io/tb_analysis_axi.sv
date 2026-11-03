`timescale 1ns/1ps
module tb_analysis_axi;
    reg clk=0;always #10 clk=~clk;
    reg rst_n=0;
    reg [11:0] s_axi_awaddr=0,s_axi_araddr=0;
    reg s_axi_awvalid=0,s_axi_wvalid=0,s_axi_bready=0,s_axi_arvalid=0,s_axi_rready=0;
    reg [31:0] s_axi_wdata=0;
    reg [3:0] s_axi_wstrb=0;
    wire s_axi_awready,s_axi_wready,s_axi_bvalid,s_axi_arready,s_axi_rvalid;
    wire [1:0] s_axi_bresp,s_axi_rresp;
    wire [31:0] s_axi_rdata;
    reg [63:0] implemented_mask=64'h5,mandatory_missing_mask=64'h3fa;
    reg [31:0] algorithm_version=0;
    reg [31:0] live_faults=0,active_config_version=0,timeout_count=0,dropped_samples=0;
    reg cfg_applied=0,cfg_rejected=0,cfg_ready=0;
    reg [31:0] cfg_response_request_id=0;
    wire cfg_valid,pause_unrelated_periodic,clear_fault,clear_counters,irq;
    wire [31:0] cfg_request_id;
    wire [63:0] ps_periodic_mask,pc_periodic_mask,ps_optional_mask,pc_optional_mask;
    reg result_valid=0;
    reg [1023:0] result_words=0;
    analysis_axi_control dut(.*);
    integer checks=0,i;
    reg [31:0] value;
    task write(input [11:0] addr,input [31:0] data,input [3:0] mask,input bit w_first,input [1:0] expected);
        begin
            if(w_first)begin
                @(negedge clk);s_axi_wdata=data;s_axi_wstrb=mask;s_axi_wvalid=1;
                @(posedge clk);while(!s_axi_wready)@(posedge clk);
                @(negedge clk);s_axi_wvalid=0;
                repeat(2)@(negedge clk);
            end
            @(negedge clk);s_axi_awaddr=addr;s_axi_awvalid=1;
            @(posedge clk);while(!s_axi_awready)@(posedge clk);
            @(negedge clk);s_axi_awvalid=0;
            if(!w_first)begin
                repeat(2)@(negedge clk);s_axi_wdata=data;s_axi_wstrb=mask;s_axi_wvalid=1;
                @(posedge clk);while(!s_axi_wready)@(posedge clk);
                @(negedge clk);s_axi_wvalid=0;
            end
            wait(s_axi_bvalid);@(negedge clk);
            if(s_axi_bresp!==expected)$fatal(1,"write response mismatch %h",addr);
            repeat(2)@(negedge clk);if(!s_axi_bvalid)$fatal(1,"write response lost under stall");
            s_axi_bready=1;@(negedge clk);s_axi_bready=0;checks=checks+1;
        end
    endtask
    task read(input [11:0] addr,input [31:0] expected,input [1:0] response);
        begin
            @(negedge clk);s_axi_araddr=addr;s_axi_arvalid=1;
            @(posedge clk);while(!s_axi_arready)@(posedge clk);
            @(negedge clk);s_axi_arvalid=0;
            wait(s_axi_rvalid);@(negedge clk);value=s_axi_rdata;
            repeat(3)@(negedge clk);
            if(!s_axi_rvalid||s_axi_rdata!==value||value!==expected||s_axi_rresp!==response)$fatal(1,"read response mismatch %h got%h expected%h",addr,value,expected);
            s_axi_rready=1;@(negedge clk);s_axi_rready=0;checks=checks+1;
        end
    endtask
    initial begin
        repeat(3)@(negedge clk);rst_n=1;
        read(0,32'h534d4131,0);read(4,32'h00010000,0);read(16,5,0);read(24,32'h3fa,0);
        read(8,0,0);
        write(12'h040,32'h00000031,15,0,0);
        write(12'h044,32'hffff0000,15,1,0);write(12'h044,32'h00001234,3,0,0);
        read(12'h044,32'hffff1234,0);
        write(12'h068,1,1,1,0);
        if(!cfg_valid||cfg_request_id!=49||ps_periodic_mask!=64'hffff1234)$fatal(1,"atomic config mismatch");
        write(12'h044,32'habcd,15,0,0);
        if(ps_periodic_mask!=64'hffff1234)$fatal(1,"pending config changed by shadow write");
        write(12'h068,1,1,0,2);
        cfg_ready=1;@(negedge clk);cfg_ready=0;repeat(2)@(negedge clk);
        if(cfg_valid)$fatal(1,"config handshake did not retire");
        cfg_applied=1;cfg_response_request_id=49;active_config_version=1;@(negedge clk);cfg_applied=0;
        read(12'h034,49,0);read(12'h030,1,0);
        for(i=0;i<32;i=i+1)result_words[i*32+:32]=32'h12300000+i;
        result_valid=1;@(negedge clk);result_valid=0;
        read(12'h024,1,0);read(12'h100,32'h12300000,0);read(12'h17c,32'h1230001f,0);
        read(12'h200,0,2);read(12'h001,0,2);write(0,0,15,0,2);
        live_faults=32'h10;repeat(2)@(negedge clk);read(12'h020,16,0);
        if(irq)$fatal(1,"IRQ must be masked until driver ready");
        write(12'h070,4,1,0,0);if(!irq)$fatal(1,"fault edge not reported");
        write(12'h028,4,1,1,0);read(12'h020,16,0);
        if(irq)$fatal(1,"persistent fault generated interrupt storm after ACK");
        live_faults=0;repeat(2)@(negedge clk);live_faults=16;repeat(2)@(negedge clk);
        if(!irq)$fatal(1,"new fault edge not rearmed");
        $display("ANALYSIS_AXI_PASS checks%0d independentAW_W strobes stable atomic capabilities errors",checks);$finish;
    end
    initial begin #200000;$fatal(1,"AXI test timeout");end
endmodule
