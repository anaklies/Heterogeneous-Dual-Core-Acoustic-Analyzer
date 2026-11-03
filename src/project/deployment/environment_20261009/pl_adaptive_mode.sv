`timescale 1ns/1ps
// Current/reference energy hysteresis. Reference freezes only after diffuse
// covariance qualification. No source class or microphone direction is vetoed.
module pl_adaptive_mode
(
    input wire clk,rst_n,arm,reference_qualified,
    input wire short_valid,short_ready,
    input wire [2:0] short_channel,
    input wire [10:0] short_bin,
    input wire signed [31:0] short_real,short_imag,
    output reg use_cnn,
    output reg clear_reference
);
    reg capturing,have_reference;
    reg [4:0] frames;
    reg [47:0] accumulator,current_energy,reference_energy;
    wire signed [15:0] re = short_real[31:16];
    wire signed [15:0] im = short_imag[31:16];
    (* use_dsp="yes" *) wire [31:0] re_power=$signed(re)*$signed(re);
    (* use_dsp="yes" *) wire [31:0] im_power=$signed(im)*$signed(im);
    wire [32:0] power={1'b0,re_power}+{1'b0,im_power};
    wire [47:0] next_energy=accumulator+power;
    wire [47:0] combined=current_energy|reference_energy;
    wire [23:0] current_norm=|combined[47:40] ? current_energy[47:24] :
        (|combined[39:24] ? current_energy[39:16] : current_energy[23:0]);
    wire [23:0] reference_norm=|combined[47:40] ? reference_energy[47:24] :
        (|combined[39:24] ? reference_energy[39:16] : reference_energy[23:0]);
    (* use_dsp="yes" *) wire [33:0] reference_scaled=reference_norm*10'd625;
    wire [33:0] current_scaled=use_cnn ? {6'b0,current_norm,4'b0} :
        ({5'b0,current_norm,5'b0}+{8'b0,current_norm,2'b0});
    reg evaluate;
    always @(posedge clk)
    begin
        if(!rst_n)
        begin
            capturing<=0;have_reference<=0;frames<=0;accumulator<=0;
            current_energy<=0;reference_energy<=0;use_cnn<=0;evaluate<=0;clear_reference<=0;
        end
        else
        begin
            evaluate<=0;clear_reference<=0;
            if(arm)
            begin
                capturing<=1;frames<=0;accumulator<=0;
            end
            if(capturing && short_valid && short_ready && short_channel==0 && short_bin<257)
            begin
                accumulator<=next_energy;
                if(short_bin==256)
                begin
                    if(frames==19)
                    begin
                        capturing<=0;current_energy<=next_energy;evaluate<=1;
                    end
                    else frames<=frames+1;
                end
            end
            if(reference_qualified && !have_reference)
            begin
                reference_energy<=current_energy;have_reference<=current_energy!=0;
                use_cnn<=current_energy!=0;
            end
            if(!reference_qualified)begin use_cnn<=0;have_reference<=0;end
            else if(evaluate && have_reference && current_energy!=0)
            begin
                // Entry ratio >=0.24; exit ratio <0.16. Middle retains mode.
                if({2'b0,reference_energy} > {current_energy,2'b0})
                begin
                    // Old loud reference no longer describes the room.
                    // Discard it before whitening can create false peaks.
                    use_cnn<=0;have_reference<=0;clear_reference<=1;
                end
                else if(use_cnn && reference_scaled<current_scaled)use_cnn<=0;
                else if(!use_cnn && reference_scaled>=current_scaled)use_cnn<=1;
            end
        end
    end
endmodule
