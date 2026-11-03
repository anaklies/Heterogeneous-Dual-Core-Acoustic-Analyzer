#include "analysis_client.h"
int sixmic_read_result(sixmic_io io,uint32_t words[32],uint32_t *epoch)
{
    if(!io.read||!words||!epoch)return -1;
    if(io.read(io.context,0)!=SIXMIC_MAGIC||io.read(io.context,4)!=SIXMIC_ABI_VERSION)return -2;
    for(unsigned attempt=0;attempt<8;attempt++) {
        uint32_t before=io.read(io.context,0x24);
        if(before==0)return -3; // No publisheddata, don't display zero as valid.
        for(unsigned i=0;i<32;i++)words[i]=io.read(io.context,0x100+4*i);
        uint32_t after=io.read(io.context,0x24);
        if(before==after){*epoch=after;return 0;}
    }
    return -4; // Snapshot changed continuously: bounded retry, caller polls later.
}
int sixmic_submit(sixmic_io io,uint32_t request,uint64_t ps1,uint64_t pc1,uint64_t ps2,uint64_t pc2,int pause)
{
    if(!io.read||!io.write)return -1;
    if(io.read(io.context,0)!=SIXMIC_MAGIC||io.read(io.context,4)!=SIXMIC_ABI_VERSION)return -2;
    uint64_t capabilities=io.read(io.context,0x10)|((uint64_t)io.read(io.context,0x14)<<32);
    if(((ps1|pc1|ps2|pc2)&~capabilities)||((ps1|pc1)&~SIXMIC_P1_MASK)||((ps2|pc2)&~SIXMIC_P2_MASK))return -5;
    if(io.read(io.context,0x18)||io.read(io.context,0x1c))return -6; // Mandatorycore not deployed.
    if(io.read(io.context,0xc)&2)return -7;
    uint32_t values[10]={request,(uint32_t)ps1,(uint32_t)(ps1>>32),(uint32_t)pc1,(uint32_t)(pc1>>32),
        (uint32_t)ps2,(uint32_t)(ps2>>32),(uint32_t)pc2,(uint32_t)(pc2>>32),(uint32_t)(pause!=0)};
    // PS andPC share ONE device-control owner. Its lock covers all shadowwrites.
    for(unsigned i=0;i<10;i++)if(io.write(io.context,0x40+4*i,values[i]))return -8;
    if(io.write(io.context,0x68,1))return -8;
    return 0;
}
int sixmic_poll_configuration(sixmic_io io,uint32_t request,uint32_t *version)
{
    if(!io.read||!version)return -1;
    uint32_t id1=io.read(io.context,0x34),v=io.read(io.context,0x30),state=io.read(io.context,0xc),id2=io.read(io.context,0x34);
    if(id1!=id2||id1!=request||(state&2))return 1; // Pending, no busy loop.
    if(state&16)return -9;
    if(!(state&8))return 1;
    *version=v;return 0;
}
