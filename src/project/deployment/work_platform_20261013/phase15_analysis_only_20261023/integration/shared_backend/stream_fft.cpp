#include <complex>
#include <cmath>
#include <cstdint>
#include "hls_fft.h"
#include "../../../phase14_room_and_pl_20261021/pl_system/analysis_dma/memory_ports.h"
#include "../../fft/hann2048.h"

struct analysis_fft_params : hls::ip_fft::params_t {
    static const unsigned log2_transform_length=11;
    static const unsigned config_width=24;
    static const unsigned implementation_options=hls::ip_fft::radix_2_burst_io;
    static const unsigned input_width=32, output_width=32;
    static const unsigned phase_factor_width=24;
    static const unsigned output_ordering=hls::ip_fft::natural_order;
    static const unsigned scaling_options=hls::ip_fft::unscaled;
    static const bool ovflo=false;
};

static void transform(hls::stream<std::complex<float>>& in,hls::stream<std::complex<float>>& out,unsigned inverse)
{
#pragma HLS INLINE off
#pragma HLS DATAFLOW
    hls::stream<hls::ip_fft::config_t<analysis_fft_params>> configs;
    hls::stream<hls::ip_fft::status_t<analysis_fft_params>> statuses;
    hls::ip_fft::config_t<analysis_fft_params> config;
    config.setDir(inverse?0:1);configs.write(config);
    hls::fft<analysis_fft_params>(in,out,statuses,configs);
    statuses.read();
}

// mode0: mean-removed normalized real PCM + periodic Hann.
// mode1: complex forward, no window. mode2: complex inverse /2048.
// mode3: mean-removed sign-extended PCM24 bits + periodic Hann.
// Offsets and stride are 32-bit words. No output writes on descriptor errors.
extern "C" void stream_fft2048(MemoryAXI memory,unsigned arena_words,
    unsigned input_offset,unsigned output_offset,unsigned stride,unsigned mode,float sample_rate,unsigned *status)
{
#pragma HLS INTERFACE m_axi port=memory offset=slave bundle=memory depth=4194304 num_read_outstanding=1 num_write_outstanding=1 max_read_burst_length=16 max_write_burst_length=16
#pragma HLS INTERFACE s_axilite port=memory bundle=control
#pragma HLS INTERFACE s_axilite port=arena_words bundle=control
#pragma HLS INTERFACE s_axilite port=input_offset bundle=control
#pragma HLS INTERFACE s_axilite port=output_offset bundle=control
#pragma HLS INTERFACE s_axilite port=stride bundle=control
#pragma HLS INTERFACE s_axilite port=mode bundle=control
#pragma HLS INTERFACE s_axilite port=sample_rate bundle=control
#pragma HLS INTERFACE s_axilite port=status bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    *status=0;
    if(!arena_words||arena_words>4194304||mode>3||!std::isfinite(sample_rate)||sample_rate<8000||sample_rate>192000||stride<1||stride>12){*status=1;return;}
    const unsigned components=(mode==1||mode==2)?2:1;
    const unsigned words=2047*stride+components;
    const unsigned output_words=(mode==0||mode==3)?7179:4096;
    if(stride<components||input_offset>arena_words||words>arena_words-input_offset||
       output_offset>arena_words||output_words>arena_words-output_offset||
       (input_offset<output_offset+output_words && output_offset<input_offset+words)){*status=2;return;}
    ReadPort source(memory,input_offset,arena_words);
    WritePort target(memory,output_offset,arena_words);
    source.length(words);target.length(output_words);
    // Explicit streams avoid synthesizing std::complex array initialization as
    // an extra frame of zero-valued FIFO writes before the actual PCM frame.
    hls::stream<std::complex<float>> in,out;
#pragma HLS STREAM variable=in depth=2048
#pragma HLS STREAM variable=out depth=2048
    float mean=0,square=0,peak=0,low=1.e30f,high=-1.e30f;unsigned clips=0;
    if(mode==0||mode==3) {
        float sum=0,correction=0;std::int64_t pcm_sum=0;
        for(unsigned i=0;i<2048;i++) {
            float value=source.get(i*stride);
            if(mode==3) {
                union {float f;std::int32_t i;} bits;bits.f=value;
                if(bits.i< -8388608||bits.i>8388607){*status=3;return;}
                pcm_sum+=bits.i;
                value=float(bits.i)*(1.f/8388608.f);
            }
            if(!std::isfinite(value)||std::fabs(value)>1.e12f){*status=3;return;}
            if(mode==0){float y=value-correction,t=sum+y;correction=(t-sum)-y;sum=t;}
            square+=value*value;peak=std::fmax(peak,std::fabs(value));low=std::fmin(low,value);high=std::fmax(high,value);clips+=(value<=-1.f||value>=8388607.f/8388608.f);
        }
        mean=mode==3?float(pcm_sum)*(1.f/(2048.f*8388608.f)):sum/2048.f;
    } else {
        // Validate the entire immutable complex frame before queuing anything.
        // An early return after a partial enqueue would poison the next job.
        for(unsigned i=0;i<2048;i++) {
            float re=source.get(i*stride),im=source.get(i*stride+1);
            if(!std::isfinite(re)||!std::isfinite(im)||std::fabs(re)>1.e12f||std::fabs(im)>1.e12f){*status=3;return;}
        }
    }
    for(unsigned i=0;i<2048;i++) {
        float re=source.get(i*stride),im=0;
        if(mode==3) {
            union {float f;std::int32_t i;} bits;bits.f=re;
            re=float(bits.i)*(1.f/8388608.f);
        } else if(components==2)im=source.get(i*stride+1);
        // The leased input may not change between validation and this pass.
        if(mode==0||mode==3)re=(re-mean)*HANN2048[i];
        in.write(std::complex<float>(re,im));
    }
    transform(in,out,mode==2);
    for(unsigned i=0;i<2048;i++) {
        const float scale=mode==2?1.f/2048.f:1.f;
        const std::complex<float> value=out.read();
        target.put(i*2,value.real()*scale);
        target.put(i*2+1,value.imag()*scale);
    }
    target.flush();
    if(mode==0||mode==3) {
        ReadPort spectrum(memory,output_offset,arena_words);spectrum.length(4096);
        float psd_scale=1.f/(sample_rate*768.f);
        for(unsigned k=0;k<=1024;k++) {
            float re=spectrum.get(2*k),im=spectrum.get(2*k+1),power=re*re+im*im;
            float one=(k==0||k==1024)?1.f:2.f;
            target.put(4096+3*k,std::sqrt(power)*one/1024.f);
            target.put(4097+3*k,power*one*psd_scale);
            target.put(4098+3*k,power*one/(2048.f*768.f));
        }
        float rms=std::sqrt(square/2048.f);
        target.put(7171,rms);target.put(7172,peak);target.put(7173,high-low);target.put(7174,mean);
        target.put(7175,rms>0?20*std::log10(rms):0);target.put(7176,rms>0?peak/rms:0);
        target.put(7177,float(clips));target.put(7178,rms>0?1:0);target.flush();
    }
}
