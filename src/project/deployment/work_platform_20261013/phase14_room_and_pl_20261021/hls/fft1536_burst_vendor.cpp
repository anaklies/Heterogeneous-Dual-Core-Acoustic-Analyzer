#include <complex>
#include <cstdint>
#include "hls_fft.h"
#include "../../phase13_pl_port_20261021/hls/fft1536_rom.h"
struct burst_fft512_params : hls::ip_fft::params_t {
    static const unsigned log2_transform_length=9;
    static const unsigned config_width=8;
    static const unsigned implementation_options=hls::ip_fft::radix_2_burst_io;
    static const unsigned input_width=24,output_width=40,phase_factor_width=24;
    static const unsigned output_ordering=hls::ip_fft::natural_order;
    static const unsigned scaling_options=hls::ip_fft::unscaled;
    static const unsigned rounding_modes=hls::ip_fft::convergent_rounding;
    static const bool ovflo=false;
};
using FIn=ap_fixed<24,1>;
// The FFT library pads each34-bit component to40bits at its C/RTL interface.
// Six extra integer sign bits preserve the23fractionbits. The unscaled API
// requires its configured output width to include the byte padding as well.
using FOut=ap_fixed<40,17>;
static void fft_fixed512(std::complex<FIn> in[512],std::complex<FOut> out[512])
{
#pragma HLS INLINE off
#pragma HLS DATAFLOW
    hls::ip_fft::config_t<burst_fft512_params> cfg;
    hls::ip_fft::status_t<burst_fft512_params> status;
    cfg.setDir(1);
    hls::fft<burst_fft512_params>(in,out,&status,&cfg);
}
extern "C" void fft1536_burst_vendor(const std::int32_t input[1536],float output[1538])
{
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=audio depth=1536
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=results depth=1538
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=output bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION function instances=fft_fixed512 limit=1
    std::complex<FIn> in[512];std::complex<FOut> out[512];
    std::complex<float> bank[1536];
    for(int r=0;r<3;r++) {
        for(int m=0;m<512;m++) {
#pragma HLS PIPELINE II=1
            int n=3*m+r;
            ap_fixed<24,1,AP_RND_CONV,AP_SAT> value=float(input[n])*FFT1536_HANN[n]/8388608.f;
            in[m]=std::complex<FIn>(value,0);
        }
        fft_fixed512(in,out);
        for(int m=0;m<512;m++) {
#pragma HLS PIPELINE II=1
            // Restore rawADC-countFFT units expected by frozenJnormalization.
            const std::complex<FOut> value=out[m];
            bank[r*512+m]=std::complex<float>(float(value.real())*8388608.f,float(value.imag())*8388608.f);
        }
    }
    for(int k=0;k<=768;k++) {
        float sr=0,si=0;
        for(int r=0;r<3;r++) {
            int wi=(r*k)%1536,src=r*512+(k%512);
            float wr=FFT1536_COS[wi],wm=FFT1536_SIN[wi],br=bank[src].real(),bi=bank[src].imag();
            sr+=wr*br-wm*bi;si+=wr*bi+wm*br;
        }
        output[2*k]=sr;output[2*k+1]=si;
    }
}
