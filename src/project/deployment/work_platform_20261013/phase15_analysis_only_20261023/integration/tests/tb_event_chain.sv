`timescale 1ns/1ps
module tb_event_chain;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,en=0,sv=0;reg[143:0]pcm=0;reg[63:0]sid=0;
 reg[31:0]source_pcm[0:12287],powers[0:12299],ram[0:524287];
 wire we,cv,cr,configured,rawfault,rawbusy;wire[31:0]base,bytes,drops,committed,offset,generation;wire[63:0]last;
 wire[31:0]wa,wd;wire[7:0]alen;wire[2:0]asize;wire[1:0]aburst;wire av,wv,wl,br;wire[3:0]ws;
 reg writing=0,bv=0;integer write_index=0,ticks=0;wire awr=!writing&&!bv;wire wr=writing&&!bv&&(ticks%5!=0);
 wire dv,db,di,rf;wire[31:0]did,doff,dframes,lost,gaps;wire[63:0]dfirst,dlast;wire[1:0]leases;
 reg fv=0,high=0;reg[63:0]ft=0;wire done,fr,fg,ff,farv,frr;wire[31:0]faddr;reg fvalid=0;reg[31:0]fdata=0;
 wire[191:0]cp;wire[255:0]bp;wire[63:0]stamp;reg[191:0]cfg=0;reg commitcfg=0;
 wire ev,started,learned;wire[63:0]et;wire[7:0]reason,bmask,efault;wire[34:0]background;
 wire [511:0]cursorwords;
 raw_cursor cursor(.clk(clk),.rst_n(rst_n),.configured(configured),.record_arm(en),.writer_enable(we),.generation(generation),.base(wa-offset),.bytes(bytes),.next_offset(offset),.dropped(drops),.faults(32'd0),.session(32'd3),.config_version(32'd7),.last_sample(last),.leased(leases),.words(cursorwords));
 wire clipready,releaseclip,releasebank;wire[31:0]releaseid;reg[511:0]clipwords;
 reg[11:0]ha=0,hr=0;reg hav=0,hwv=0,hbr=1,harv=0,hrr=1;reg[31:0]hwd=0;
 wire hawr,hwr,hbv,harr,hrv;wire[31:0]hrd;wire[1:0]hbre,hre;reg[31:0]capt[0:15];integer fileout;
 always @(posedge clk)begin
  ticks<=ticks+1;
  if(av&&awr)begin
   if(wa<32'h100000||wa>=32'h300000||alen!=7||asize!=2||aburst!=1)$fatal(1,"raw range/burst");
   writing<=1;write_index<=(wa-32'h100000)/4;
  end
  if(wv&&wr)begin ram[write_index]<=wd;write_index<=write_index+1;if(wl)begin writing<=0;bv<=1;end end
  if(bv&&br)bv<=0;
  if(farv)begin
   if(faddr<32'h10000||((faddr-32'h10000)%32768)<4098*4)$fatal(1,"feature address");
   fdata<=powers[(high?6150:0)+((faddr-32'h10000)/32768)*1025+(((faddr-32'h10000)%32768)-4098*4)/12];fvalid<=1;
  end
  if(fvalid&&frr)fvalid<=0;
 end
 pcm_axi_ring_writer writer(.clk(clk),.rst_n(rst_n),.enable(we),.clear_fault(1'b0),.cfg_valid(cv),.cfg_ready(cr),.cfg_base(base),.cfg_bytes(bytes),.cfg_reserved_low(32'h100000),.cfg_reserved_high(32'h300000),.cfg_rejected(),.configured(configured),.sample_valid(sv),.pcm(pcm),.sample_id(sid),.dropped_samples(drops),.committed_samples(committed),.last_committed_sample_id(last),.next_write_offset(offset),.region_generation(generation),.fault_latched(rawfault),.bus_timeout(),.bus_response_error(),.busy(rawbusy),.m_axi_awaddr(wa),.m_axi_awlen(alen),.m_axi_awsize(asize),.m_axi_awburst(aburst),.m_axi_awvalid(av),.m_axi_awready(awr),.m_axi_wdata(wd),.m_axi_wstrb(ws),.m_axi_wlast(wl),.m_axi_wvalid(wv),.m_axi_wready(wr),.m_axi_bresp(2'b0),.m_axi_bvalid(bv),.m_axi_bready(br));
 fft_event_features features(.clk(clk),.rst_n(rst_n),.frame_valid(fv),.frame_base(32'h10000),.frame_last(ft),.band_mask(8'b0),.band_edges(256'b0),.done_valid(done),.done_ready(fr),.feature_valid(fg),.channel_power(cp),.band_power(bp),.timestamp(stamp),.fault(ff),.araddr(faddr),.arvalid(farv),.arready(1'b1),.rdata(fdata),.rresp(2'b0),.rvalid(fvalid),.rlast(1'b1),.rready(frr));
 event_power_detector detector(.clk(clk),.rst_n(rst_n),.cfg_commit(commitcfg),.cfg_data(cfg),.in_valid(done),.feature_valid(fg),.in_ready(fr),.sample_timestamp(stamp),.channel_power(cp),.band_power(bp),.out_valid(ev),.out_ready(1'b1),.out_timestamp(et),.config_generation(),.out_config_generation(),.out_reason(reason),.out_band_mask(bmask),.out_started(started),.out_ended(),.out_active(),.learned(learned),.background_power(background),.background_bands(),.sticky_fault(efault));
 event_recorder #(.PRE(4),.POST(6),.MAX_SAMPLES(64)) recorder(.clk(clk),.rst_n(rst_n),.enable(en),.sample_valid(sv),.event_start(ev&&started),.event_sample(et),.last_committed(last),.committed(committed),.next_offset(offset),.writer_drops(drops),.writer_cfg_ready(cr),.writer_cfg_accepted(cv&&cr),.bank0_base(32'h100000),.bank1_base(32'h200000),.bank_bytes(32'h100000),.reserved_low(32'h100000),.reserved_high(32'h300000),.writer_enable(we),.writer_cfg_valid(cv),.writer_cfg_base(base),.writer_cfg_bytes(bytes),.release_valid(releaseclip),.release_bank(releasebank),.release_id(releaseid),.descriptor_valid(dv),.descriptor_ready(clipready),.descriptor_bank(db),.descriptor_id(did),.descriptor_start_offset(doff),.descriptor_frames(dframes),.descriptor_first(dfirst),.descriptor_last(dlast),.descriptor_incomplete(di),.leased(leases),.lost_events(lost),.handoff_drops(gaps),.fault(rf),.capturing());
 always @*begin
  clipwords=0;clipwords[31:0]=did;clipwords[63:32]=db?32'h200000:32'h100000;clipwords[95:64]=doff;clipwords[127:96]=dframes;clipwords[191:128]=dfirst;clipwords[255:192]=dlast;clipwords[287:256]={31'b0,di};clipwords[319:288]=3;clipwords[351:320]=7;clipwords[383:352]={16'b0,bmask,reason};
 end
 runtime_control #(.CFG_WORDS(32),.PROTOCOL(3)) control(.clk(clk),.rst_n(rst_n),.awaddr(ha),.awvalid(hav),.awready(hawr),.wdata(hwd),.wstrb(4'hf),.wvalid(hwv),.wready(hwr),.bresp(hbre),.bvalid(hbv),.bready(hbr),.araddr(hr),.arvalid(harv),.arready(harr),.rdata(hrd),.rresp(hre),.rvalid(hrv),.rready(hrr),.cfg_valid(),.cfg_ready(1'b0),.cfg_applied(1'b0),.cfg_rejected(1'b0),.cfg_payload(),.raw_cursor_words(cursorwords),.result_valid(1'b0),.result_words(1024'b0),.live_faults(32'b0),.active_config(32'd7),.clip_valid(dv),.clip_bank_in(db),.clip_words(clipwords),.clip_ready(clipready),.clip_release(releaseclip),.clip_bank(releasebank),.clip_id(releaseid),.irq());
 task sample(input integer n,input integer gain);
 begin @(negedge clk);for(integer c=0;c<6;c=c+1)pcm[24*c+:24]=$signed(source_pcm[c*2048+n%2048])*gain;
 sid=n;sv=1;@(negedge clk);sv=0;repeat(63)@(negedge clk);end endtask
 task feature(input integer frame);
 begin @(negedge clk);high=frame==2;ft=frame*2048+2047;fv=1;@(negedge clk);fv=0;while(!done)@(negedge clk);repeat(4)@(negedge clk);end endtask
 task get(input[11:0]a,output[31:0]value);
 begin @(negedge clk);hr=a;harv=1;while(!harr)@(negedge clk);@(negedge clk);harv=0;while(!hrv)@(negedge clk);if(hre)$fatal(1,"read error");value=hrd;@(negedge clk);end endtask
 task put(input[11:0]a,input[31:0]value);
 begin @(negedge clk);ha=a;hwd=value;hav=1;while(!hawr)@(negedge clk);@(negedge clk);hav=0;hwv=1;while(!hwr)@(negedge clk);@(negedge clk);hwv=0;while(!hbv)@(negedge clk);if(hbre)$fatal(1,"write error");@(negedge clk);end endtask
 initial begin
 $readmemh("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/tests/pcm_window.hex",source_pcm);
 $readmemh("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/tests/event_chain_fft_powers.hex",powers);
 cfg[3:0]=7;cfg[31:16]=512;cfg[47:32]=512;cfg[63:48]=128;cfg[79:64]=2;cfg[95:80]=1;cfg[111:96]=8;cfg[127:112]=1;cfg[159:128]=1024;cfg[163:160]=4;cfg[191:176]=2048;
 repeat(4)@(negedge clk);rst_n=1;en=1;commitcfg=1;@(negedge clk);commitcfg=0;while(!we)@(negedge clk);
 for(integer f=0;f<3;f=f+1)begin for(integer i=0;i<2048;i=i+1)sample(f*2048+i,f==2?8:1);while(rawbusy)@(negedge clk);feature(f);end
 if(!learned||efault||ff||rawfault||rf)$fatal(1,"chain fault or not learned");
 for(integer n=6144;n<6156;n=n+1)sample(n,1);
 repeat(40)@(negedge clk);
 get('h300,capt[0]);if(capt[0]!=32'h43555231)$fatal(1,"cursor MMIO missing");
 for(integer i=0;i<16;i=i+1)get('h200+i*4,capt[i]);
 if(capt[3]!=11||capt[4]!=6139||capt[6]!=6149||capt[8]!=0||!leases[0]||capt[11][7:0]!=1)$fatal(1,"clip metadata wrong frames%0d first%0d last%0d incomplete%0d reason%h",capt[3],capt[4],capt[6],capt[8],capt[11]);
 fileout=$fopen("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/tests/event_chain_capture.hex","w");
 for(integer i=0;i<16;i=i+1)$fdisplay(fileout,"%08h",capt[i]);
 for(integer i=0;i<11*8;i=i+1)$fdisplay(fileout,"%08h",ram[(capt[2]/4+i)%262144]);$fclose(fileout);
 put('h2c,capt[0]);put('h28,1);repeat(4)@(negedge clk);if(leases[0])$fatal(1,"host release did not release raw bank");
 if(drops||lost||rf||rawfault||ff||efault)$fatal(1,"silent data loss/fault");
 $display("EVENT_CHAIN_PASS PCM_records FFT_feature_DDR detector writer_drain sealed_clip mailbox host_read_release frames11 first6139 last6149");$finish;
 end
 initial begin #20000000;$fatal(1,"chain timeout");end
endmodule
