#include <cstdio>
#include <cmath>
#include "../../../phase14_room_and_pl_20261021/pl_system/analysis_dma/memory_ports.h"
extern "C" void stream_fft2048(MemoryAXI,unsigned,unsigned,unsigned,unsigned,unsigned,float,unsigned*);
// Co-simulation marshals the declared m_axi depth, even with a smaller arena_words.
static float arena[4194304];
int main(){
 FILE *input=std::fopen("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/tests/pcm_window.hex","r");
 FILE *gold=std::fopen("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/tests/stream_golden.txt","r");
 if(!input||!gold)return 1;
 unsigned status;
 arena[42]=NAN;
 stream_fft2048(arena,32768,32,20000,2,1,48000,&status);
 if(status!=3)return 6;
 for(unsigned i=0;i<12288;i++){union{unsigned u;float f;}v;if(std::fscanf(input,"%x",&v.u)!=1)return 2;arena[32+i]=v.f;}
 unsigned checks=0;
 for(unsigned c=0;c<6;c++){
  stream_fft2048(arena,32768,32+c*2048,20000,1,3,48000,&status);if(status)return 3;
  for(unsigned i=0;i<7179;i++){
   float expected;if(std::fscanf(gold,"%f",&expected)!=1)return 4;
   float atol=i<4096?4.e-5f:2.e-5f;
   if(i>=4096&&i<7171&&((i-4096)%3)==1)atol=1.e-11f;
   if(i>=4096&&i<7171&&((i-4096)%3)==2)atol=1.e-9f;
   if(!std::isfinite(arena[20000+i])||!std::isfinite(expected)||std::fabs(arena[20000+i]-expected)>atol+std::fabs(expected)*3.e-4f){std::printf("mismatch channel%u at%u got%.9g expected%.9g\n",c,i,arena[20000+i],expected);return 5;}
   checks++;
  }
 }
 std::printf("SERIAL_RTL_PCM_STREAM_FFT_PSD_LEVELS_C_PASS channels=6 checks=%u\n",checks);
 return 0;
}
