#include <cmath>
#include <cstdio>
#include <cstdint>
extern "C" void fft1536_fixed_vendor(const std::int32_t*,float*);
static const char* root="C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase14_room_and_pl_20261021";
int main()
{
    std::int32_t input[1536];float output[1538];
    for(int test=0;test<2;test++) {
        for(int n=0;n<1536;n++)input[n]=test==0?(n==333?838861:0):(std::int32_t)(167772*std::sin(2*3.141592653589793*37*n/1536));
        fft1536_fixed_vendor(input,output);double maximum=0;
        for(int k=0;k<=768;k++) {
            double re=0,im=0;
            for(int n=0;n<1536;n++) {
                double v=input[n]*(.5-.5*std::cos(2*3.141592653589793*n/1536));
                re+=v*std::cos(2*3.141592653589793*k*n/1536);im-=v*std::sin(2*3.141592653589793*k*n/1536);
            }
            maximum=std::fmax(maximum,std::hypot(re-output[2*k],im-output[2*k+1]));
        }
        std::printf("FIXED_FFT_CASE%d_MAX_RAW_COUNT_ERROR %.9g\n",test,maximum);
        if(maximum>100)return 1;
    }
    char name[1024];std::snprintf(name,sizeof name,"%s/examples/feature_pcm.bin",root);
    FILE* f=std::fopen(name,"rb");if(!f)return 2;
    static std::int32_t pcm[11776*6];if(std::fread(pcm,4,11776*6,f)!=11776*6)return 3;std::fclose(f);
    std::snprintf(name,sizeof name,"%s/results/fixed_fft_stft.bin",root);f=std::fopen(name,"wb");if(!f)return 4;
    for(int ch=0;ch<6;ch++)for(int t=0;t<27;t++) {
        for(int n=0;n<1536;n++)input[n]=pcm[(t*384+n)*6+ch];
        fft1536_fixed_vendor(input,output);
        for(int bin=4;bin<=252;bin+=4)std::fwrite(output+2*bin,4,2,f);
    }
    std::fclose(f);std::puts("FIXED_FFT_CMODEL_PASS162TRANSFORMS");return 0;
}
