`timescale 1ns / 1ps
module tb_axi_activity_guard;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0;
    reg awvalid=0,awready=0,wvalid=0,wready=0,wlast=0,bvalid=0,bready=0;
    reg arvalid=0,arready=0,rvalid=0,rready=0,rlast=0;
    reg [1:0] bresp=0,rresp=0;
    reg clear_response_fault=0;
    wire quiescent,response_fault,protocol_fault;
    wire [31:0] error_responses,pending_reads,pending_write_addresses,pending_write_data;
    integer checks=0;
    axi_activity_guard #(.MAX_PENDING(2)) dut(.*);
    task tick;begin @(posedge clk);#1;@(negedge clk);end endtask
    task check(input bit ok,input string why);
        begin checks++;if(!ok)$fatal(1,"%0d:%s",checks,why);end
    endtask
    initial begin
        tick;rst_n=1;tick;check(quiescent,"reset idle");
        awvalid=1;tick;check(!quiescent && pending_write_addresses==0,"stalled VALID prevents reset");
        awready=1;tick;awvalid=0;awready=0;
        check(pending_write_addresses==1 && !quiescent,"AW outstanding");
        wvalid=1;wready=1;wlast=0;tick;
        check(!quiescent && pending_write_data==0,"partial write packet");
        wlast=1;tick;wvalid=0;wready=0;wlast=0;
        check(pending_write_data==1 && !quiescent,"WLAST still needs B");
        bvalid=1;bready=1;tick;bvalid=0;bready=0;#1;
        check(quiescent && !protocol_fault,"write drained");
        // AXI permits write data before its address.
        wvalid=1;wready=1;wlast=1;tick;wvalid=0;wready=0;wlast=0;
        check(!quiescent && pending_write_data==1,"W before AW retained");
        awvalid=1;awready=1;tick;awvalid=0;awready=0;
        bvalid=1;bready=1;bresp=2;tick;bvalid=0;bready=0;bresp=0;#1;
        check(quiescent && response_fault && error_responses==1,"SLVERR drain is known");
        clear_response_fault=1;tick;clear_response_fault=0;
        check(!response_fault,"safe error ack");
        arvalid=1;arready=1;tick;arvalid=0;arready=0;
        check(pending_reads==1 && !quiescent,"read burst outstanding");
        rvalid=1;rready=1;rlast=0;rresp=3;tick;rresp=0;
        check(pending_reads==1 && response_fault,"read error does not finish burst");
        clear_response_fault=1;tick;clear_response_fault=0;
        check(response_fault,"cannot clear while active");
        rlast=1;tick;rvalid=0;rready=0;rlast=0;#1;
        check(quiescent && !protocol_fault,"read last drains");
        // A B response with no corresponding AW/data invalidates the model.
        bvalid=1;bready=1;tick;bvalid=0;bready=0;#1;
        check(protocol_fault && !quiescent,"orphan response blocks unsafe reset");
        rst_n=0;tick;rst_n=1;tick;check(quiescent,"common bus reset recovery");
        arvalid=1;arready=1;repeat(3)tick;arvalid=0;arready=0;
        check(protocol_fault && !quiescent,"overflow never wraps to idle");
        rst_n=0;tick;rst_n=1;tick;
        awvalid=1;awready=1;wvalid=1;wready=1;wlast=1;bvalid=1;bready=1;
        tick;awvalid=0;awready=0;wvalid=0;wready=0;wlast=0;bvalid=0;bready=0;#1;
        check(protocol_fault && !quiescent,"new AW and WLAST cannot hide orphan B");
        rst_n=0;tick;rst_n=1;tick;
        arvalid=1;arready=1;rvalid=1;rready=1;rlast=1;
        tick;arvalid=0;arready=0;rvalid=0;rready=0;rlast=0;#1;
        check(protocol_fault && !quiescent,"new AR cannot hide orphan RLAST");
        $display("AXI_ACTIVITY_GUARD_PASS checks=%0d",checks);$finish;
    end
    initial begin #10000;$fatal(1,"timeout");end
endmodule
