#include <stdint.h>
#include "fft1536_rom.h"

// Exact length 1536 = 3 * 512, not a padded2048 approximation.
// Forward FFT sign and periodic Hann match the frozen neural feature path.
static void fft_stage(float re[1536],float im[1536],int offset,int stage)
{
#pragma HLS INLINE off
    int half=1<<stage;
    for(int butterfly=0;butterfly<256;butterfly++) {
#pragma HLS PIPELINE II=4
        // At a fixed stage these512 addresses form a permutation: no two
        // butterflies touch the same element. Calls between stages are serial.
        int j=butterfly&(half-1);
        int base=(butterfly>>stage)<<(stage+1);
        int a=offset+base+j,b=a+half;
        int wi=3*(j<<(8-stage));
        float wr=FFT1536_COS[wi],si=FFT1536_SIN[wi];
        float br=re[b],bi=im[b],ar=re[a],ai=im[a];
        float p0=wr*br,p1=si*bi,p2=wr*bi,p3=si*br;
        float tr=p0-p1,ti=p2+p3;
        re[a]=ar+tr;im[a]=ai+ti;re[b]=ar-tr;im[b]=ai-ti;
    }
}

static void fft512(float re[1536], float im[1536], int offset)
{
#pragma HLS INLINE off
    for (int i=0;i<512;i++) {
        unsigned reverse=0;
        for(int b=0;b<9;b++) reverse=(reverse<<1)|((i>>b)&1);
        if(reverse>(unsigned)i) {
            float r=re[offset+i],v=im[offset+i];
            re[offset+i]=re[offset+reverse];im[offset+i]=im[offset+reverse];
            re[offset+reverse]=r;im[offset+reverse]=v;
        }
    }
    for(int stage=0;stage<9;stage++)fft_stage(re,im,offset,stage);
}

extern "C" void fft1536_hann(const float input[1536],float output[1538])
{
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=audio depth=1536
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=results depth=1538
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=output bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION function instances=fft512 limit=1
    float re[1536],im[1536];
#pragma HLS BIND_STORAGE variable=re type=ram_2p impl=bram
#pragma HLS BIND_STORAGE variable=im type=ram_2p impl=bram
    for(int r=0;r<3;r++) {
        for(int m=0;m<512;m++) {
#pragma HLS PIPELINE II=1
            int n=3*m+r;
            re[r*512+m]=input[n]*FFT1536_HANN[n];im[r*512+m]=0;
        }
        fft512(re,im,r*512);
    }
    for(int k=0;k<=768;k++) {
        float sr=0,si=0;
        for(int r=0;r<3;r++) {
            int wi=(r*k)%1536,src=r*512+(k%512);
            float wr=FFT1536_COS[wi],wim=FFT1536_SIN[wi];
            sr+=wr*re[src]-wim*im[src];si+=wr*im[src]+wim*re[src];
        }
        output[2*k]=sr;output[2*k+1]=si;
    }
}
