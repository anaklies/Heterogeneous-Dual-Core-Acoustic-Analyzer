#include <cstdio>
#include <cmath>
#include <complex>
#include "../../phase14_room_and_pl_20261021/pl_system/analysis_dma/memory_ports.h"
extern "C" void analysis_fft2048(MemoryAXI,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned*);
static float arena[32768];
int main() {
    unsigned status,checks=0;
    FILE *in=std::fopen("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/fft/vectors.txt","r");
    if(!in)return 1;
    for(unsigned test=0;test<5;test++) {
        unsigned mode,stride;
        if(std::fscanf(in,"%u %u",&mode,&stride)!=2)return 2;
        for(unsigned i=0;i<32768;i++)arena[i]=0;
        for(unsigned i=0;i<2048;i++) {
            float re,im;std::fscanf(in,"%f %f",&re,&im);
            if(mode==3){union {float f;int i;} bits;bits.i=(int)re;arena[32+i*stride]=bits.f;}
            else {arena[32+i*stride]=re;if(mode==1||mode==2)arena[33+i*stride]=im;}
        }
        analysis_fft2048(arena,32768,32,20000,stride,mode,&status);
        if(status){std::printf("badstatus test%u %u\n",test,status);return 3;}
        float maximum=0;
        for(unsigned i=0;i<4096;i++) {
            float expected;std::fscanf(in,"%f",&expected);
            float error=std::fabs(arena[20000+i]-expected);
            if(error>maximum)maximum=error;
            if(error>2.e-4f+std::fabs(expected)*2.e-5f){std::printf("FFT mismatch test%u at%u %.9g %.9g\n",test,i,arena[20000+i],expected);return 4;}
            ++checks;
        }
        std::printf("case%u mode%u maximum_error %.9g\n",test,mode,maximum);
    }
    std::fclose(in);
    arena[20000]=123;
    analysis_fft2048(arena,32768,32,20000,0,0,&status);
    if(status!=1||arena[20000]!=123)return 5;
    analysis_fft2048(arena,32768,32,1000,1,0,&status);
    if(status!=2)return 6;
    arena[32]=NAN;
    analysis_fft2048(arena,32768,32,20000,1,0,&status);
    if(status!=3||arena[20000]!=123)return 7;
    std::puts("SHARED_FFT_VENDOR_CSIM_PASS_20480_VALUES_3_INVALID");
    return 0;
}
