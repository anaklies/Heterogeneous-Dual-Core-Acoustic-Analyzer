#include <cmath>
#include <cstdio>
#include "../../phase14_room_and_pl_20261021/pl_system/analysis_dma/memory_ports.h"
extern "C" void analysis_fft2048(MemoryAXI,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned*);
extern "C" void analysis_dma_safe(MemoryAXI,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,float,float,unsigned*);
static float arena[32768];
int main() {
 unsigned status,checks=0;
 // Six distinct tones and a DC offset prove strided PCM24 decoding and detrend.
 for(unsigned i=0;i<2048;i++)for(unsigned c=0;c<6;c++) {
   float amp=.125f*(c+1);
   union {float f;int i;} bits;
   bits.i=(int)std::round((amp*std::sin(6.283185307179586*(31+c*17)*i/2048)+.02)*8388608.);
   arena[32+i*6+c]=bits.f;
 }
 for(unsigned c=0;c<6;c++) {
   analysis_fft2048(arena,32768,32+c,20000,6,3,&status);
   if(status)return 1;
   analysis_dma_safe(arena,20000,16000,25000,32768,2048,0,2,48000.f/2048,0,&status);
   if(status)return 2;
   float energy=0,peak=-1;unsigned at=0;
   for(unsigned k=0;k<1025;k++) {
     float amp=arena[25000+3*k],psd=arena[25001+3*k];
     if(amp>peak){peak=amp;at=k;}
     energy+=arena[25002+3*k];
     arena[30000+k]=psd;
   }
   if(at!=31+c*17 || std::fabs(peak-.125*(c+1))>2.e-5)return 3;
   if(std::fabs(energy-.5*.125*.125*(c+1)*(c+1))>2.e-5)return 4;
   if(std::fabs(arena[25000])>2.e-5)return 5;
   arena[16000]=0;arena[16001]=24001;
   analysis_dma_safe(arena,30000,16000,29000,32768,1025,1,8,48000.f/2048,0,&status);
   if(status||std::fabs(arena[29000]-energy)>2.e-5)return 6;
   checks+=4;
 }
 std::printf("PCM24_FFT_PSD_BAND_C_CONNECTION_PASS channels=6 checks=%u no_RTL_schedule_claim\n",checks);
 return 0;
}
