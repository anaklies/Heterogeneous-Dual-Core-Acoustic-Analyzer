`timescale 1ns/1ps
module tb_pcm_writer;
    reg clk=0;always #10 clk=~clk;
    reg rst_n=0,enable=0,clear_fault=0,cfg_valid=0,sample_valid=0;
    reg [31:0] cfg_base=32'h1000,cfg_bytes=4096,cfg_reserved_low=32'h1000,cfg_reserved_high=32'h3000;
    reg [143:0] pcm=0;
    reg [63:0] sample_id=0;
    wire cfg_ready,cfg_rejected,configured,busy,fault_latched,bus_timeout,bus_response_error;
    wire [31:0] dropped_samples,committed_samples,next_write_offset,m_axi_awaddr,m_axi_wdata;
    wire [31:0] region_generation;
    wire [63:0] last_committed_sample_id;
    wire [7:0] m_axi_awlen;
    wire [2:0] m_axi_awsize;
    wire [1:0] m_axi_awburst;
    wire [3:0] m_axi_wstrb;
    wire m_axi_awvalid,m_axi_wvalid,m_axi_wlast,m_axi_bready;
    reg m_axi_awready=0,m_axi_wready=0,m_axi_bvalid=0;
    reg [1:0] m_axi_bresp=0;
    reg stall=0,inject_error=0;
    reg [31:0] rng=32'h1321d;
    integer jobs=0,words=0,cycles=0,checks=0,i,c,expected;
    pcm_axi_ring_writer #(.FIFO_DEPTH(8),.BUS_TIMEOUT_CYCLES(100)) dut(.*);
    function integer value(input integer id,input integer channel);
        value=(channel%2)?-(id*37+channel):(id*37+channel);
    endfunction
    always @(negedge clk) begin
        rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
        m_axi_awready<=!stall&&rng[0];m_axi_wready<=!stall&&rng[1];
    end
    always @(posedge clk) if(rst_n)begin
        cycles=cycles+1;if(cycles>20000)$fatal(1,"writer timeout");
        if(m_axi_awvalid&&m_axi_awready)begin
            jobs=jobs+1;words=0;
            if(m_axi_awaddr!=32'h1000+((committed_samples%128)*32)||m_axi_awlen!=7||m_axi_awsize!=2||m_axi_awburst!=1)$fatal(1,"burst address/bounds");
            if(m_axi_awaddr[11:0]>4064)$fatal(1,"4KiB crossing");checks=checks+1;
        end
        if(m_axi_wvalid&&m_axi_wready)begin
            if(words<6)expected=value(jobs,words);else expected=words==6?jobs:0;
            if(m_axi_wdata!==expected||m_axi_wlast!=(words==7)||m_axi_wstrb!=15)$fatal(1,"PCM format mismatch job%0d word%0d",jobs,words);
            checks=checks+1;words=words+1;
            if(m_axi_wlast)begin m_axi_bvalid<=1;m_axi_bresp<=inject_error?2:0;end
        end
        if(m_axi_bvalid&&m_axi_bready)m_axi_bvalid<=0;
    end
    task send_sample(input integer id);
        begin
            @(negedge clk);sample_id=id;
            for(c=0;c<6;c=c+1)pcm[c*24+:24]=value(id,c);
            sample_valid=1;@(negedge clk);sample_valid=0;
        end
    endtask
    initial begin
        repeat(3)@(negedge clk);rst_n=1;
        cfg_valid=1;@(negedge clk);cfg_valid=0;
        if(!configured)$fatal(1,"valid reserved region rejected");enable=1;
        for(i=1;i<=200;i=i+1)begin send_sample(i);repeat(40)@(negedge clk);end
        wait(committed_samples==200);@(negedge clk);
        if(dropped_samples||last_committed_sample_id!=200||next_write_offset!=2304)$fatal(1,"ring wrap/commit");
        stall=1;inject_error=1;send_sample(201);repeat(110)@(negedge clk);
        if(!fault_latched||!bus_timeout||!m_axi_awvalid)$fatal(1,"watchdog violated inflight AXI");
        stall=0;wait(bus_response_error);repeat(2)@(negedge clk);
        if(committed_samples!=200||dropped_samples!=1)$fatal(1,"failed burst counted successful");
        clear_fault=1;@(negedge clk);clear_fault=0;inject_error=0;send_sample(202);
        wait(committed_samples==201);@(negedge clk);
        if(last_committed_sample_id!=202||fault_latched)$fatal(1,"writer recovery");
        wait(!busy);@(negedge clk);enable=0;cfg_base=32'h2000;cfg_reserved_high=32'h4000;
        cfg_valid=1;@(negedge clk);cfg_valid=0;@(negedge clk);
        if(region_generation!=2||committed_samples||last_committed_sample_id||next_write_offset)$fatal(1,"new region leaked old descriptor");
        $display("PCM_AXI_WRITER_PASS checks%0d committed201 oneExplicitError ringWrap",checks);$finish;
    end
endmodule
