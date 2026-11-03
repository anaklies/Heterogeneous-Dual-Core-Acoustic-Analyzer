`timescale 1ns / 1ps
module tb_profile_scheduler;
    localparam [63:0] P0 = 64'h3ff;
    localparam [63:0] P1 = 64'hc00;
    localparam [63:0] P2 = 64'h300000;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n=0,frame_start=0,cfg_valid=0,pause_p1=0;
    reg [31:0] frame_id=0,request_id=0;
    reg [63:0] implemented=P0|P1|P2,ps_p1=0,pc_p1=0,ps_p2=0,pc_p2=0;
    reg engine_busy=0,engine_done=0,engine_progress=0,clear_fault=0,clear_counters=0;
    reg [31:0] engine_tid=0,engine_version=0;
    wire cfg_ready,cfg_applied,cfg_rejected,mandatory_ready;
    wire [31:0] response_request,active_version;
    wire [63:0] unsupported,capabilities,missing,active_p1,active_p2;
    wire job_start,job_cancel,engine_reset,result_publish,stale_done,fault_latched,running;
    wire [63:0] job_mask;
    wire [31:0] job_frame,job_tid,job_version,completed_tid,completed_version;
    wire [3:0] error_code;
    wire [7:0] strikes;
    wire [31:0] missed,canceled,timeouts,stales;
    integer checks=0,cycles,i,j;

    profile_scheduler #(.MANDATORY_MASK(P0),.PERIODIC_MASK(P1),.OPTIONAL_MASK(P2),
        .JOB_TIMEOUT_CYCLES(16),.STALL_TIMEOUT_CYCLES(8),.RESET_CYCLES(3)) dut(
        .clk(clk),.rst_n(rst_n),.frame_start(frame_start),.frame_id(frame_id),.implemented_mask(implemented),
        .cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_request_id(request_id),
        .ps_periodic_mask(ps_p1),.pc_periodic_mask(pc_p1),.ps_optional_mask(ps_p2),.pc_optional_mask(pc_p2),
        .pause_unrelated_periodic(pause_p1),.cfg_applied(cfg_applied),.cfg_rejected(cfg_rejected),
        .cfg_response_request_id(response_request),.cfg_unsupported_mask(unsupported),
        .active_config_version(active_version),.capabilities(capabilities),.mandatory_ready(mandatory_ready),
        .mandatory_missing_mask(missing),.active_periodic_mask(active_p1),.active_optional_mask(active_p2),
        .engine_busy(engine_busy),.engine_done(engine_done),.engine_progress(engine_progress),
        .engine_transaction_id(engine_tid),.engine_config_version(engine_version),
        .job_start(job_start),.job_cancel(job_cancel),.engine_reset(engine_reset),.job_mask(job_mask),
        .job_frame_id(job_frame),.job_transaction_id(job_tid),.job_config_version(job_version),
        .result_publish(result_publish),.stale_done(stale_done),.completed_transaction_id(completed_tid),
        .completed_config_version(completed_version),.clear_fault(clear_fault),.clear_counters(clear_counters),
        .fault_latched(fault_latched),.last_error_code(error_code),.consecutive_timeouts(strikes),
        .missed_frames(missed),.canceled_jobs(canceled),.timeout_count(timeouts),.stale_done_count(stales),
        .running(running)
    );

    task tick;
        begin @(posedge clk); #1; end
    endtask
    task check(input bit condition,input [511:0] message);
        begin checks=checks+1; if(!condition) $fatal(1,"CHECK %0d FAILED: %0s",checks,message); end
    endtask
    task frame(input [31:0] id);
        begin frame_id=id;frame_start=1;tick();frame_start=0;end
    endtask
    task done;
        begin
            engine_busy=1;engine_tid=job_tid;engine_version=job_version;engine_progress=1;
            tick();engine_progress=0;engine_busy=0;engine_done=1;tick();engine_done=0;
            check(result_publish,"matching result publishes");
            check(completed_tid==job_tid && completed_version==job_version,"published metadata matches");
            tick();
        end
    endtask
    task configure(input [31:0] id);
        begin
            check(cfg_ready,"configuration slot available");request_id=id;cfg_valid=1;tick();cfg_valid=0;
            check(!cfg_ready && !cfg_applied,"configuration waits for next frame");
        end
    endtask
    task wait_reset;
        begin
            engine_busy=0;
            for(j=0;j<5;j=j+1) tick();
            check(!engine_reset,"warm reset finite");
        end
    endtask

    initial begin
        repeat(3) tick();rst_n=1;wait_reset();
        check(capabilities==implemented && mandatory_ready,"only integrated capabilities advertised");
        frame(0);check(job_start && job_mask==P0,"mandatory ten every frame");done();

        ps_p1=64'h400;pc_p1=64'h800;configure(1);
        check(active_version==0 && active_p1==0,"pending values not visible mid-frame");
        frame(1);check(cfg_applied && active_version==1 && response_request==1,"atomic config commit");
        check(active_p1==P1 && job_mask==P0,"PS-PC periodic union, decimated frame1");done();
        frame(2);check(job_mask==(P0|P1),"P1 every second frame");done();

        ps_p2=64'h100000;pc_p2=64'h200000;pause_p1=1;configure(2);
        frame(3);check(job_mask==(P0|P2) && active_p2==P2,"P2 union immediate on config, P0 retained");done();
        for(i=4;i<14;i=i+1) begin
            frame(i);check(job_mask==P0,"P2 waits11frames and unrelated P1 paused");done();
        end
        frame(14);check(job_mask==(P0|P2),"P2 repeats after11frames");done();
        pc_p2=0;configure(3);frame(15);
        check(job_mask==(P0|64'h100000) && active_p2==64'h100000,"PC page exit retains PS subscription");done();

        pc_p2=64'h8000000000000000;cfg_valid=1;request_id=4;tick();cfg_valid=0;
        check(cfg_rejected && unsupported[63] && active_version==3,"unsupported request rejected, no fictitious core");
        pc_p2=0;

        frame(16);check(job_start,"new batch started");
        engine_done=1;engine_tid=job_tid+1;engine_version=job_version;tick();engine_done=0;
        check(stale_done && !result_publish && running,"wrong transaction cannot publish or finish");done();

        // A new version cancels an old in-flight batch and suppresses its stale result.
        frame(17);engine_busy=1;engine_tid=job_tid;engine_version=job_version;
        ps_p2=0;pause_p1=0;configure(5);frame(18);
        check(job_cancel && engine_reset && !running && active_version==4,"config switch cancels old batch safely");
        engine_done=1;tick();engine_done=0;
        check(stale_done && !result_publish,"late canceled completion is stale");wait_reset();

        for(i=0;i<3;i=i+1) begin
            frame(100+i);check(job_start,"retry permitted before third timeout");engine_busy=1;
            engine_tid=job_tid;engine_version=job_version;
            cycles=0;
            while(!job_cancel && cycles<30) begin tick();cycles=cycles+1;end
            check(job_cancel && error_code==4,"no-progress timeout is bounded");
            check(strikes==i+1,"consecutive timeout counter");wait_reset();
        end
        check(fault_latched,"third failure latches fault instead of infinite restarts");
        frame(110);check(!job_start,"latched fault prevents restart loop");
        clear_counters=1;tick();clear_counters=0;
        check(fault_latched && timeouts==0,"counter clear does not rearm fault");
        clear_fault=1;tick();clear_fault=0;wait_reset();
        check(!fault_latched && strikes==0,"explicit fault rearm separate from history clear");

        frame(111);engine_busy=1;engine_tid=job_tid;engine_version=job_version;engine_progress=1;
        cycles=0;
        while(!job_cancel && cycles<30) begin tick();cycles=cycles+1;end
        engine_progress=0;
        check(job_cancel && error_code==3,"continuous progress cannot defeat absolute deadline");wait_reset();
        frame(112);done();check(strikes==0,"successful batch clears consecutive timeout strikes");

        engine_busy=1;cycles=0;
        while(!job_cancel && cycles<30) begin tick();cycles=cycles+1;end
        check(job_cancel && error_code==5,"orphan busy is bounded even without dispatched job");wait_reset();

        implemented=P0 & ~64'h8;frame(113);
        check(!mandatory_ready && missing==64'h8 && !job_start && error_code==2,"missing P0 not falsely accepted");
        check(capabilities==implemented,"capability query stays truthful");
        $display("CONTROL_SCHEDULER_PASS checks=%0d",checks);
        $finish;
    end
    initial begin #1000000;$fatal(1,"Testbench watchdog");end
endmodule
