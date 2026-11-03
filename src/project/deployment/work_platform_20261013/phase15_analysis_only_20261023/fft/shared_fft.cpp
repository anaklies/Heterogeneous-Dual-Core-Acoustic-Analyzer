#include <complex>
#include <cmath>
#include <cstdint>
#include "hls_fft.h"
#include "../../phase14_room_and_pl_20261021/pl_system/analysis_dma/memory_ports.h"
#include "hann2048.h"

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

static void transform(std::complex<float> in[2048],std::complex<float> out[2048],unsigned inverse)
{
#pragma HLS INLINE off
#pragma HLS DATAFLOW
    hls::ip_fft::config_t<analysis_fft_params> config;
    hls::ip_fft::status_t<analysis_fft_params> status;
    config.setDir(inverse?0:1);
    hls::fft<analysis_fft_params>(in,out,&status,&config);
}

// mode0: mean-removed normalized real PCM + periodic Hann.
// mode1: complex forward, no window. mode2: complex inverse /2048.
// mode3: mean-removed sign-extended PCM24 bits + periodic Hann.
// Offsets and stride are 32-bit words. No output writes on descriptor errors.
extern "C" void analysis_fft2048(MemoryAXI memory,unsigned arena_words,
    unsigned input_offset,unsigned output_offset,unsigned stride,unsigned mode,unsigned *status)
{
#pragma HLS INTERFACE m_axi port=memory offset=slave bundle=memory depth=4194304 num_read_outstanding=1 num_write_outstanding=1 max_read_burst_length=16 max_write_burst_length=16
#pragma HLS INTERFACE s_axilite port=memory bundle=control
#pragma HLS INTERFACE s_axilite port=arena_words bundle=control
#pragma HLS INTERFACE s_axilite port=input_offset bundle=control
#pragma HLS INTERFACE s_axilite port=output_offset bundle=control
#pragma HLS INTERFACE s_axilite port=stride bundle=control
#pragma HLS INTERFACE s_axilite port=mode bundle=control
#pragma HLS INTERFACE s_axilite port=status bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    *status=0;
    if(!arena_words||arena_words>4194304||mode>3||stride<1||stride>12){*status=1;return;}
    const unsigned components=(mode==1||mode==2)?2:1;
    const unsigned words=2047*stride+components;
    if(stride<components||input_offset>arena_words||words>arena_words-input_offset||
       output_offset>arena_words||4096>arena_words-output_offset||
       (input_offset<output_offset+4096 && output_offset<input_offset+words)){*status=2;return;}
    ReadPort source(memory,input_offset,arena_words);
    WritePort target(memory,output_offset,arena_words);
    source.length(words);target.length(4096);
    std::complex<float> in[2048],out[2048];
    float mean=0;
    if(mode==0||mode==3) {
        float sum=0;
        for(unsigned i=0;i<2048;i++) {
            float value=source.get(i*stride);
            if(mode==3) {
                union {float f;std::int32_t i;} bits;bits.f=value;
                if(bits.i< -8388608||bits.i>8388607){*status=3;return;}
                value=float(bits.i)*(1.f/8388608.f);
            }
            if(!std::isfinite(value)||std::fabs(value)>1.e12f){*status=3;return;}
            sum+=value;
        }
        mean=sum/2048.f;
    }
    for(unsigned i=0;i<2048;i++) {
        float re=source.get(i*stride),im=0;
        if(mode==3) {
            union {float f;std::int32_t i;} bits;bits.f=re;
            if(bits.i< -8388608||bits.i>8388607){*status=3;return;}
            re=float(bits.i)*(1.f/8388608.f);
        } else if(components==2)im=source.get(i*stride+1);
        if(!std::isfinite(re)||!std::isfinite(im)||std::fabs(re)>1.e12f||std::fabs(im)>1.e12f){*status=3;return;}
        if(mode==0||mode==3)re=(re-mean)*HANN2048[i];
        in[i]=std::complex<float>(re,im);
    }
    transform(in,out,mode==2);
    for(unsigned i=0;i<2048;i++) {
        const float scale=mode==2?1.f/2048.f:1.f;
        const std::complex<float> value=out[i];
        target.put(i*2,value.real()*scale);
        target.put(i*2+1,value.imag()*scale);
    }
    target.flush();
}
