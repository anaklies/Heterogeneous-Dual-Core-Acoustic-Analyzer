#include "../interfaces/analysis_client.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct fixture {uint32_t regs[1024];unsigned writes;int move_once,move_always;};
static uint32_t read32(void *v,uint32_t offset)
{
    struct fixture *f=v;
    if(offset==0x140&&(f->move_once||f->move_always)) {
        f->regs[0x24/4]++;
        for(unsigned i=0;i<32;i++)f->regs[0x100/4+i]=0x1000+i;
        f->move_once=0;
    }
    return f->regs[offset/4];
}
static int write32(void *v,uint32_t offset,uint32_t value)
{
    struct fixture *f=v;f->writes++;f->regs[offset/4]=value;
    if(offset==0x68)f->regs[0xc/4]=2;
    return 0;
}
int main(void)
{
    struct fixture f;memset(&f,0,sizeof f);sixmic_io io={&f,read32,write32};
    f.regs[0]=SIXMIC_MAGIC;f.regs[1]=SIXMIC_ABI_VERSION;
    uint32_t out[32],epoch,version;
    assert(sixmic_read_result(io,out,&epoch)==-3);
    f.regs[0x24/4]=1;for(unsigned i=0;i<32;i++)f.regs[0x100/4+i]=i;
    assert(sixmic_read_result(io,out,&epoch)==0&&out[31]==31&&epoch==1);
    f.move_once=1;assert(sixmic_read_result(io,out,&epoch)==0&&out[31]==0x101f&&epoch==2);
    f.move_always=1;assert(sixmic_read_result(io,out,&epoch)==-4);f.move_always=0;
    uint64_t caps=SIXMIC_P0_MASK|SIXMIC_P1_MASK|SIXMIC_P2_MASK;
    f.regs[0x10/4]=(uint32_t)caps;f.regs[0x14/4]=(uint32_t)(caps>>32);
    assert(sixmic_submit(io,7,SIXMIC_FN_OCTAVE,0,SIXMIC_FN_ROOM_DECAY,0,1)==0);
    assert(f.writes==11&&f.regs[0x40/4]==7);
    assert(sixmic_poll_configuration(io,7,&version)==1);
    f.regs[0x34/4]=7;f.regs[0x30/4]=9;f.regs[0xc/4]=8;
    assert(sixmic_poll_configuration(io,7,&version)==0&&version==9);
    f.regs[0xc/4]=10;assert(sixmic_poll_configuration(io,7,&version)==1); // oldACKwhilepending
    f.regs[0xc/4]=16;assert(sixmic_poll_configuration(io,7,&version)==-9);
    f.regs[0xc/4]=0;f.regs[0x14/4]=0;f.regs[0x10/4]=0;
    assert(sixmic_submit(io,8,SIXMIC_FN_OCTAVE,0,0,0,0)==-5&&f.writes==11);
    f.regs[0x10/4]=(uint32_t)caps;f.regs[0x14/4]=(uint32_t)(caps>>32);f.regs[0x18/4]=1;
    assert(sixmic_submit(io,9,0,0,0,0,0)==-6);
    puts("CLIENT_PROTOCOL_PASS boundedretry capabilities pending staleACK generation");return 0;
}
