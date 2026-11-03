`timescale 1ns / 1ps
module feature_bus(input wire clk, rst_n, clear, input integer case_id,
    input wire [31:0] addr, input wire av, output wire ar,
    output reg [31:0] data, output reg [1:0] resp,
    output reg rv, output reg last, input wire rr, output integer reads);
    integer cycles=0, delay_count=0;
    reg pending=0;
    assign ar=!pending && !rv && cycles%5!=0;
    function [31:0] value(input integer n, input integer c);
        begin
            case(c)
                0:value=0;
                1:value={1'b0,8'd102,23'((n*3791)^32'h5719)};
                2:value=32'h3f800000;
                3:case(n%7)
                    0:value=32'hbf800000;
                    1:value=32'h7fc00000;
                    2:value=32'h00000001;
                    3:value={1'b0,8'd97,23'h671234};
                    4:value={1'b0,8'd119,23'h571234};
                    5:value={1'b0,8'd128,23'h771234};
                    default:value={1'b0,8'd129,23'h171234};
                endcase
                default:value=32'h35800000;
            endcase
        end
    endfunction
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(!rst_n || clear) begin reads<=0; pending<=0; rv<=0; resp<=0; last<=1; end
        else begin
            if(av && ar) begin
                if(addr!=32'h100000+(reads/1025)*32768+(4098+3*(reads%1025))*4)
                    $fatal(1,"read order case=%0d read=%0d",case_id,reads);
                data<=value(reads,case_id); resp<=(case_id==5 && reads==119)?2:0;
                last<=!(case_id==6 && reads==119);
                delay_count<=(case_id==7 && reads==0)?110:reads%4;
                pending<=1; reads<=reads+1;
            end
            if(pending && !rv) begin
                if(delay_count==0) rv<=1;
                else delay_count<=delay_count-1;
            end
            if(rv && rr) begin rv<=0; pending<=0; end
        end
    end
endmodule

module tb_features_equivalence;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0, valid=0, ready=0, clear=0;
    integer cid=0, ticks=0, start_at, old_cycles, new_cycles, worst=0;
    reg [255:0] edges=0;
    wire [1:0] done, good, fault, av, ar, rv, rr, last;
    wire [31:0] addr[0:1],data[0:1];
    wire [1:0] resp[0:1];
    wire [191:0] channels[0:1]; wire [255:0] bands[0:1]; wire [63:0] ts[0:1];
    wire signed [31:0] reads[0:1];
    always @(posedge clk) begin
        ticks<=ticks+1;
        if(done[0] && old_cycles==0) old_cycles<=ticks-start_at;
        if(done[1] && new_cycles==0) new_cycles<=ticks-start_at;
    end
    fft_event_features_reference #(.TIMEOUT(96)) old_core(
        .clk(clk),.rst_n(rst_n),.frame_valid(valid),.frame_base(32'h100000),
        .frame_last(64'd8191),.band_mask(8'hff),.band_edges(edges),
        .done_valid(done[0]),.done_ready(ready),.feature_valid(good[0]),
        .channel_power(channels[0]),.band_power(bands[0]),.timestamp(ts[0]),.fault(fault[0]),
        .araddr(addr[0]),.arvalid(av[0]),.arready(ar[0]),.rdata(data[0]),
        .rresp(resp[0]),.rvalid(rv[0]),.rlast(last[0]),.rready(rr[0]));
    fft_event_features #(.TIMEOUT(96)) new_core(
        .clk(clk),.rst_n(rst_n),.frame_valid(valid),.frame_base(32'h100000),
        .frame_last(64'd8191),.band_mask(8'hff),.band_edges(edges),
        .done_valid(done[1]),.done_ready(ready),.feature_valid(good[1]),
        .channel_power(channels[1]),.band_power(bands[1]),.timestamp(ts[1]),.fault(fault[1]),
        .araddr(addr[1]),.arvalid(av[1]),.arready(ar[1]),.rdata(data[1]),
        .rresp(resp[1]),.rvalid(rv[1]),.rlast(last[1]),.rready(rr[1]));
    for(genvar g=0;g<2;g=g+1) begin
        feature_bus bus(.clk(clk),.rst_n(rst_n),.clear(clear),.case_id(cid),
            .addr(addr[g]),.av(av[g]),.ar(ar[g]),.data(data[g]),.resp(resp[g]),
            .rv(rv[g]),.last(last[g]),.rr(rr[g]),.reads(reads[g]));
    end
    initial begin
        repeat(3) @(negedge clk); rst_n=1;
        for(cid=0;cid<8;cid=cid+1) begin
            for(integer b=0;b<8;b=b+1) begin
                edges[32*b +: 16]=b*97;
                edges[32*b+16 +: 16]=1025-b*19;
            end
            if(cid==4) edges[31:0]={16'd1026,16'd1025};
            clear=1; @(negedge clk); clear=0;
            old_cycles=0; new_cycles=0; start_at=ticks; valid=1;
            @(negedge clk); valid=0;
            while(done!=3) @(negedge clk);
            @(negedge clk);
            if(channels[0]!==channels[1] || bands[0]!==bands[1] ||
               good[0]!==good[1] || fault[0]!==fault[1] || ts[0]!==ts[1] || reads[0]!=reads[1])
                $fatal(1,"differential mismatch case=%0d oldgood=%b newgood=%b",cid,good[0],good[1]);
            if(cid<5 && reads[1]!=6150) $fatal(1,"missing input samples");
            if(new_cycles>200000) $fatal(1,"feature budget exceeded");
            if(new_cycles>worst) worst=new_cycles;
            repeat(4) @(negedge clk);
            if(done!=3) $fatal(1,"output not retained");
            $display("FEATURE_EQ_CASE %0d old=%0d new=%0d reads=%0d valid=%b",cid,old_cycles,new_cycles,reads[1],good[1]);
            ready=1; @(negedge clk); ready=0;
        end
        $display("FEATURE_EQ_PASS cases=8 exact_all_outputs max_cycles=%0d",worst); $finish;
    end
    initial begin #20000000; $fatal(1,"watchdog"); end
endmodule
