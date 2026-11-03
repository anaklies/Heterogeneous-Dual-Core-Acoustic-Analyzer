#include "memory_ports.h"
#include <cmath>
#include <cstdio>
extern "C" void analysis_dma_safe(MemoryAXI,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,float,float,unsigned*);
static float memory[16384];
int main()
{
    unsigned status=999;
    for(int k=0;k<17;k++){memory[100+2*k]=1;memory[100+2*k+1]=0;}
    analysis_dma_safe(memory,100,1024,4096,16384,32,0,2,1500,0,&status);
    if(status)return 1;
    for(int k=0;k<17;k++) {
        float one=(k==0||k==16)?1.f:2.f;
        if(std::fabs(memory[4096+3*k+1]-one/(48000.f*12.f))>1e-10)return 2;
        if(std::fabs(memory[4096+3*k+2]-one/384.f)>1e-7)return 3;
    }
    for(int i=0;i<12;i+=2){memory[128+i]=1;memory[128+i+1]=0;memory[1024+i]=std::cos(.5f);memory[1024+i+1]=std::sin(.5f);}
    analysis_dma_safe(memory,128,1024,512,16384,3,2,5,1,1,&status);
    if(status)return 4;
    for(int k=0;k<3;k++)if(std::fabs(memory[512+7*k+4]-1)>1e-6 || std::fabs(memory[512+7*k+5]-.5f)>1e-4)return 5;
    for(int i=0;i<16;i++)for(int c=0;c<6;c++)memory[200+6*i+c]=.125f*(c+1);
    analysis_dma_safe(memory,200,1024,800,16384,16,0,1,1,0,&status);
    if(status)return 6;
    for(int c=0;c<6;c++)if(std::fabs(memory[800+8*c]-.125f*(c+1))>1e-6)return 7;
    memory[16380]=123;
    analysis_dma_safe(memory,100,1024,16380,16384,33,0,3,1,0,&status);
    if(status!=14 || memory[16380]!=123)return 8;
    analysis_dma_safe(memory,100,1024,4096,16384,3,0,4,1,-1,&status);
    if(status!=4)return 9;
    analysis_dma_safe(memory,100,1024,4096,16384,3,0,4,1,4294967296.f,&status);
    if(status!=4)return 10;
    std::puts("ANALYSIS_DMA_VENDOR_TRANSPORT_PASS3OPERATIONS_BOUNDARY_REJECT");
    return 0;
}
