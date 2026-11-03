#include <cmath>
#include <cstdio>
#include "../../phase14_room_and_pl_20261021/pl_system/analysis_dma/memory_ports.h"
extern "C" void analysis_dma_safe(MemoryAXI,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,float,float,unsigned*);
static float arena[32768];
int main() {
    unsigned status=99;
    for(unsigned i=0;i<17;i++){arena[32+i]=i;arena[256+i]=16-i;}
    analysis_dma_safe(arena,32,256,10000,32768,17,0,14,1,0,&status);
    if(status)return 1;
    for(unsigned i=0;i<17;i++)if(arena[10000+i]!=(i>8?i:16-i))return 2;
    double energy=0;
    for(unsigned i=0;i<4096;i++){float v=std::exp(-float(i)/400);arena[32+i]=v;energy+=double(v)*v;}
    analysis_dma_safe(arena,32,8000,10000,32768,4096,0,17,48000,0,&status);
    if(status)return 3;
    if(std::fabs(arena[10000]-energy)>.002)return 4;
    for(unsigned i=1;i<4096;i++)if(arena[10000+2*i]>arena[10000+2*(i-1)])return 5;
    for(unsigned i=0;i<4096;i++)arena[32+i]=-60*float(i)/48000/.1f;
    arena[8000]=-5;arena[8001]=-25;
    analysis_dma_safe(arena,32,8000,10000,32768,4096,0,19,48000,.9,&status);
    if(status||arena[10004]!=1||std::fabs(arena[10000]-.1)>.00001)return 6;
    arena[33]=123;
    analysis_dma_safe(arena,32,8000,33,32768,17,0,14,1,0,&status);
    if(status!=14||arena[33]!=123)return 7;
    std::puts("EXTENDED_VENDOR_TRANSPORT_PASS_PEAK_DECAY_FIT_ALIAS_REJECT");
    return 0;
}
