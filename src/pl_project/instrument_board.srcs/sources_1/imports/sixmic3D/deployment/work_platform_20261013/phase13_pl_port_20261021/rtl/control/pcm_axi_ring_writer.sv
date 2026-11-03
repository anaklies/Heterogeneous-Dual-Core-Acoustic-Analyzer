`timescale 1ns / 1ps
// One outstanding AXI burst. Each sample is8 little-endian32-bit words:
// six sign-extendedPCM24 channels, then64-bit monotonically supplied sampleID.
// Configuration must refer to OS-reservedDDR, never an arbitrary Linux buffer.
module pcm_axi_ring_writer #(
    parameter integer FIFO_DEPTH=32,
    parameter integer BUS_TIMEOUT_CYCLES=491620
)(
    input wire clk,rst_n,enable,clear_fault,
    input wire cfg_valid,
    output wire cfg_ready,
    input wire [31:0] cfg_base,cfg_bytes,cfg_reserved_low,cfg_reserved_high,
    output reg cfg_rejected,configured,
    input wire sample_valid,
    input wire [143:0] pcm,
    input wire [63:0] sample_id,
    output reg [31:0] dropped_samples,committed_samples,
    output reg [63:0] last_committed_sample_id,
    output reg [31:0] next_write_offset,
    output reg [31:0] region_generation,
    output reg fault_latched,bus_timeout,bus_response_error,
    output wire busy,
    output wire [31:0] m_axi_awaddr,
    output wire [7:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output wire m_axi_awvalid,
    input wire m_axi_awready,
    output wire [31:0] m_axi_wdata,
    output wire [3:0] m_axi_wstrb,
    output wire m_axi_wlast,m_axi_wvalid,
    input wire m_axi_wready,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready
);
    localparam integer PW=$clog2(FIFO_DEPTH);
    localparam integer CW=$clog2(FIFO_DEPTH+1);
    localparam IDLE=0,ADDRESS=1,DATA=2,RESPONSE=3;
    reg [1:0] state;
    (* ram_style="distributed" *) reg [207:0] fifo[0:FIFO_DEPTH-1];
    reg [PW-1:0] write_pointer,read_pointer;
    reg [CW-1:0] count;
    reg [207:0] current;
    reg [2:0] word;
    reg [31:0] base,length,age;
    wire config_legal=cfg_base[11:0]==0 && cfg_bytes>=4096 &&
        (cfg_bytes&(cfg_bytes-1))==0 && cfg_base>=cfg_reserved_low &&
        {1'b0,cfg_base}+{1'b0,cfg_bytes}<={1'b0,cfg_reserved_high} &&
        cfg_reserved_high>cfg_reserved_low;
    wire popping=state==RESPONSE&&m_axi_bvalid;
    wire accepting=sample_valid&&enable&&configured&&!fault_latched&&(count<FIFO_DEPTH||popping);
    assign cfg_ready=state==IDLE&&count==0&&!enable;
    assign busy=state!=IDLE||count!=0;
    assign m_axi_awaddr=base+next_write_offset;
    assign m_axi_awlen=7;
    assign m_axi_awsize=2;
    assign m_axi_awburst=1;
    assign m_axi_awvalid=state==ADDRESS;
    assign m_axi_wdata=word<6 ? {{8{current[word*24+23]}},current[word*24+:24]} :
                                        (word==6?current[175:144]:current[207:176]);
    assign m_axi_wstrb=4'hf;
    assign m_axi_wlast=word==7;
    assign m_axi_wvalid=state==DATA;
    assign m_axi_bready=state==RESPONSE;
    wire progress=(m_axi_awvalid&&m_axi_awready)||(m_axi_wvalid&&m_axi_wready)||(m_axi_bvalid&&m_axi_bready);
    wire [1:0] losses={1'b0,(sample_valid&&enable&&!accepting)}+{1'b0,(popping&&m_axi_bresp!=0)};
    initial if(FIFO_DEPTH<2||(FIFO_DEPTH&(FIFO_DEPTH-1))!=0||BUS_TIMEOUT_CYCLES<1)
        $fatal(1,"invalid PCM writer capacity/timeout");
    always @(posedge clk) begin
        if(!rst_n) begin
            state<=IDLE;word<=0;count<=0;write_pointer<=0;read_pointer<=0;current<=0;
            base<=0;length<=0;next_write_offset<=0;configured<=0;cfg_rejected<=0;
            fault_latched<=0;bus_timeout<=0;bus_response_error<=0;age<=0;
            dropped_samples<=0;committed_samples<=0;last_committed_sample_id<=0;
            region_generation<=0;
        end else begin
            cfg_rejected<=0;
            if(cfg_valid&&cfg_ready) begin
                if(config_legal)begin
                    base<=cfg_base;length<=cfg_bytes;next_write_offset<=0;configured<=1;
                    region_generation<=region_generation+1;committed_samples<=0;last_committed_sample_id<=0;
                end
                else begin cfg_rejected<=1;configured<=0;end
            end
            if(losses!=0)
                dropped_samples<=dropped_samples>32'hffffffff-losses?32'hffffffff:dropped_samples+losses;
            if(accepting)begin fifo[write_pointer]<={sample_id,pcm};write_pointer<=write_pointer+1;end
            case({accepting,popping})
                2'b10:count<=count+1;
                2'b01:count<=count-1;
            endcase
            if(popping)read_pointer<=read_pointer+1;
            if(state==IDLE||progress)age<=0;
            else if(age<BUS_TIMEOUT_CYCLES)age<=age+1;
            if(state!=IDLE&&age>=BUS_TIMEOUT_CYCLES-1&&!progress)begin
                fault_latched<=1;bus_timeout<=1;
                // Do not violate AXI by dropping an already accepted burst.
                // Stop NEW jobs; keep in-flightVALID/data until the bus responds.
            end
            if(clear_fault&&state==IDLE)begin fault_latched<=0;bus_timeout<=0;bus_response_error<=0;end
            case(state)
                IDLE:if(count!=0&&!fault_latched)begin current<=fifo[read_pointer];word<=0;state<=ADDRESS;end
                ADDRESS:if(m_axi_awready)state<=DATA;
                DATA:if(m_axi_wready)begin
                    if(word==7)state<=RESPONSE;
                    else word<=word+1;
                end
                RESPONSE:if(m_axi_bvalid)begin
                    state<=IDLE;
                    if(m_axi_bresp!=0)begin fault_latched<=1;bus_response_error<=1;end
                    else begin
                        if(committed_samples!=32'hffffffff)committed_samples<=committed_samples+1;
                        last_committed_sample_id<=current[207:144];
                        next_write_offset<=next_write_offset==length-32?0:next_write_offset+32;
                    end
                end
            endcase
        end
    end
endmodule
