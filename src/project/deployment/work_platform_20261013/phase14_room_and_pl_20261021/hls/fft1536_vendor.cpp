#include <complex>
#include "hls_fft.h"
#include "../../phase13_pl_port_20261021/hls/fft1536_rom.h"

struct fft512_params : hls::ip_fft::params_t {
    static const unsigned log2_transform_length=9;
    static const unsigned input_width=32,output_width=32;
    static const unsigned phase_factor_width=24;
    static const unsigned output_ordering=hls::ip_fft::natural_order;
    static const unsigned scaling_options=hls::ip_fft::unscaled;
    static const bool ovflo=false;
};

static void transform512(std::complex<float> in[512],std::complex<float> out[512])
{
#pragma HLS INLINE off
#pragma HLS DATAFLOW
    // AMDFFT512 is shared across the three radix3 components.
    hls::ip_fft::config_t<fft512_params> config;
    hls::ip_fft::status_t<fft512_params> status;
    config.setDir(1);
    // The2025.2 convenienceAPI unconditionally sets a scaling schedule even
    // forunscaledFFT. The supported config/statusAPI avoids that hostassert.
    hls::fft<fft512_params>(in,out,&status,&config);
}

extern "C" void fft1536_vendor(const float input[1536],float output[1538])
{
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=audio depth=1536
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=results depth=1538
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=output bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION function instances=transform512 limit=1
    std::complex<float> in[512],out[512],bank[1536];
    for(int r=0;r<3;r++) {
        for(int m=0;m<512;m++) {
#pragma HLS PIPELINE II=1
            int n=3*m+r;
            in[m]=std::complex<float>(input[n]*FFT1536_HANN[n],0);
        }
        transform512(in,out);
        for(int m=0;m<512;m++) {
#pragma HLS PIPELINE II=1
            bank[r*512+m]=out[m];
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
