`timescale 1ns/1ps
// Fixed-point summary detector. This module does not accept PCM.
module event_power_detector (
 input logic clk, rst_n,
 input logic cfg_commit,
 input logic [191:0] cfg_data,
 input logic in_valid, input logic feature_valid,
 output logic in_ready,
 input logic [63:0] sample_timestamp,
 input logic [191:0] channel_power,
 input logic [255:0] band_power,
 output logic out_valid, input logic out_ready,
 output logic [63:0] out_timestamp,
 output logic [31:0] config_generation, out_config_generation,
 output logic [7:0] out_reason, out_band_mask,
 output logic out_started, out_ended, out_active,
 output logic learned,
 output logic [34:0] background_power,
 output logic [255:0] background_bands,
 output logic [7:0] sticky_fault
);
 // cfg: control[3:0]={adapt,lock,relearn,enable}; mask[15:8].
 // Q8 rise[31:16], band rise[47:32], loss[63:48].
 // learn/release/max/cooldown blocks[79:64]/[95:80]/[111:96]/[127:112].
 // power floor[159:128], adapt shift[163:160], block samples[191:176].
 logic [191:0] cfg;
 logic [15:0] learn_count,release_count,active_count,cooldown;
 logic active, have_timestamp;
 logic [63:0] last_timestamp;
 logic [34:0] sum_power;
 logic [7:0] reasons, changed_bands;
 logic cfg_legal, change_on;
 integer i;
 function automatic [34:0] adapt35(input [34:0] oldval,newval,input [3:0] shift);
   if(newval>=oldval) adapt35=oldval+((newval-oldval)>>shift);
   else adapt35=oldval-((oldval-newval)>>shift);
 endfunction
 function automatic [31:0] adapt32(input [31:0] oldval,newval,input [3:0] shift);
   if(newval>=oldval) adapt32=oldval+((newval-oldval)>>shift);
   else adapt32=oldval-((oldval-newval)>>shift);
 endfunction
 always_comb begin
   sum_power=0;
   for(integer c=0;c<6;c=c+1) sum_power=sum_power+{3'b0,channel_power[c*32+:32]};
   cfg_legal=(cfg_data[31:16]>256 && cfg_data[47:32]>256 && cfg_data[63:48]<256 &&
     cfg_data[79:64]!=0 && cfg_data[95:80]!=0 && cfg_data[111:96]!=0 &&
     cfg_data[191:176]!=0 && cfg_data[159:128]!=0 && cfg_data[163:160]!=0 &&
     cfg_data[7:4]==0 && cfg_data[175:164]==0);
   reasons=0; changed_bands=0;
   // Explicit extension prevents expression truncation before multiplication.
   if(({21'b0,sum_power}<<8) >= ({21'b0,background_power}*{40'b0,cfg[31:16]}) &&
       sum_power >= {3'b0,cfg[159:128]}) reasons[0]=1;
   if(({21'b0,sum_power}<<8) <= ({21'b0,background_power}*{40'b0,cfg[63:48]}) &&
       background_power >= {3'b0,cfg[159:128]}) reasons[2]=1;
   for(integer b=0;b<8;b=b+1)
     if(cfg[8+b] && band_power[b*32+:32]>=cfg[159:128] &&
       ({24'b0,band_power[b*32+:32]}<<8) >=
       ({24'b0,background_bands[b*32+:32]}*{40'b0,cfg[47:32]})) changed_bands[b]=1;
   reasons[1]=|changed_bands;
   change_on=|reasons;
   in_ready=(!out_valid || out_ready) && !cfg_commit;
 end
 always_ff @(posedge clk) begin
   if(!rst_n) begin
     cfg<=0;learn_count<=0;release_count<=0;active_count<=0;cooldown<=0;
     active<=0;have_timestamp<=0;last_timestamp<=0;learned<=0;
     background_power<=0;background_bands<=0;sticky_fault<=0;
     out_valid<=0;out_timestamp<=0;out_reason<=0;out_band_mask<=0;
     config_generation<=0;out_config_generation<=0;
     out_started<=0;out_ended<=0;out_active<=0;
   end else begin
     if(out_valid && out_ready) out_valid<=0;
     if(cfg_commit) begin
       if(!cfg_legal || config_generation==32'hffffffff) sticky_fault[0]<=1;
       else begin
         cfg<=cfg_data;
         config_generation<=config_generation+1'b1;
         // Config boundary terminates event state; old pending output is preserved.
         active<=0;release_count<=0;active_count<=0;cooldown<=0;
         if(cfg_data[1]) begin
           learned<=0;learn_count<=0;background_power<=0;background_bands<=0;
         end
       end
     end else if(in_valid && in_ready) begin
       if(!feature_valid) sticky_fault[1]<=1;
       else if(have_timestamp && sample_timestamp<=last_timestamp) sticky_fault[2]<=1;
       else begin
         // Forward gaps consume only the time marker, never learn/trigger on missing data.
         have_timestamp<=1; last_timestamp<=sample_timestamp;
         if(have_timestamp && (last_timestamp > (64'hffffffffffffffff-{48'b0,cfg[191:176]}) ||
            sample_timestamp!=last_timestamp+{48'b0,cfg[191:176]})) begin
           sticky_fault[3]<=1;active<=0;release_count<=0;active_count<=0;
         end else begin
           out_valid<=1;out_timestamp<=sample_timestamp;out_reason<=0;out_band_mask<=0;
           out_config_generation<=config_generation;
           out_started<=0;out_ended<=0;out_active<=active;
           if(!cfg[0]) begin
             active<=0;out_active<=0;
           end else if(!learned) begin
             // Deterministic IIR warm-up, including an exact seed on first block.
             if(learn_count==0) begin
               background_power<=sum_power;background_bands<=band_power;
             end else begin
               background_power<=adapt35(background_power,sum_power,cfg[163:160]);
               for(i=0;i<8;i=i+1) background_bands[i*32+:32]<=
                 adapt32(background_bands[i*32+:32],band_power[i*32+:32],cfg[163:160]);
             end
             if(learn_count+17'd1 >= {1'b0,cfg[79:64]}) learned<=1;
             else learn_count<=learn_count+1'b1;
           end else begin
             out_reason<=reasons;out_band_mask<=changed_bands;
             if(cooldown!=0) cooldown<=cooldown-1'b1;
             if(!active && cooldown==0 && change_on) begin
               active<=1;out_active<=1;out_started<=1;active_count<=1;release_count<=0;
               if(cfg[111:96]==1) begin
                 active<=0;out_active<=0;out_ended<=1;cooldown<=cfg[127:112];
               end
             end else if(active) begin
               // New changes before release extend the same event (merge).
               if(change_on) release_count<=0;
               else release_count<=release_count+1'b1;
               active_count<=active_count+1'b1;
               if(active_count+17'd1 >= {1'b0,cfg[111:96]} ||
                 (!change_on && release_count+17'd1 >= {1'b0,cfg[95:80]})) begin
                 active<=0;out_active<=0;out_ended<=1;cooldown<=cfg[127:112];
                 // No implicit background rebase, especially when locked.
               end
             end
             if(cfg[3] && !cfg[2] && !active && !change_on && cooldown==0) begin
               background_power<=adapt35(background_power,sum_power,cfg[163:160]);
               for(i=0;i<8;i=i+1) background_bands[i*32+:32]<=
                 adapt32(background_bands[i*32+:32],band_power[i*32+:32],cfg[163:160]);
             end
           end
         end
       end
     end
   end
 end
endmodule
