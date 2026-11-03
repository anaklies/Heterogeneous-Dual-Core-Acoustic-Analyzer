#include "gateway.h"
#include "feature_runtime.h"
#include <string.h>
#define TABLE_A 524288u
#define TABLE_B 528384u
#define CONTEXT_A 540672u
#define CONTEXT_B 532480u
static int overlap(uint32_t a,uint32_t n,uint32_t b,uint32_t m){return(uint64_t)a+n>b&&(uint64_t)b+m>a;}
int echo_prepare_config(gw*g,uint32_t words[32],const char**reason){
    uint32_t desc[16][4][16],zero[80]={0},current,next,context;unsigned i,slot;
    if(!g->service_route_count)return 0;
    if(!g->config_active_known||!g->mmio->write_private){*reason="managed_profile_not_ready";return -1;}
    current=g->config_active_words[6];
    if((current!=TABLE_A&&current!=TABLE_B)||words[6]!=current||words[15]>=g->service_route_count||words[30]!=64||((words[8]&SM_P2_ENABLE)&&!echo_features_internal_config(g))){*reason="portable_profile_layout_is_managed";return -1;}
    for(i=2;i<=7;i++)if(i!=6&&words[i]!=g->config_active_words[i]){*reason="hot_profile_replacement_is_not_allowed";return -1;}
    next=current==TABLE_A?TABLE_B:TABLE_A;context=next==TABLE_A?CONTEXT_A:CONTEXT_B;
    for(i=0;i<g->service_route_count;i++)for(slot=0;slot<4;slot++){
        uint32_t*d=desc[i][slot],address=0x10000000u+4*(current+64*i+16*slot);
        if(g->mmio->mem.invalidate(g->mmio->mem.ctx,address,64)||g->mmio->mem.read(g->mmio->mem.ctx,address,d,16)){*reason="descriptor_read_failed";return -1;}
        if(d[0]!=0x414c5531u||d[11]!=g->config_active_words[0]||d[12]!=g->active_config_version||!d[3]||d[3]>1024||d[4]<524288||d[7]<524288||d[2]<524288){*reason="active_descriptor_identity_mismatch";return -1;}
        if(overlap(d[2],4*d[3],context,5120)||overlap(d[4],80,context,5120)||overlap(d[7],d[8],context,5120)||overlap(d[2],4*d[3],next,1024)||overlap(d[4],80,next,1024)||overlap(d[7],d[8],next,1024)){*reason="inactive_pool_overlaps_active_work";return -1;}
        d[4]=context+i*320+slot*80;d[11]=words[0];d[12]=words[1];
    }
    /* Old commands can only reach the active descriptor/context pool. Build the
     * other pool first, then let the existing IDLE-only config handshake switch
     * pointers. No active program/code/output or P0 storage is overwritten. */
    for(i=0;i<g->service_route_count;i++)for(slot=0;slot<4;slot++){
        uint32_t*d=desc[i][slot];
        if(g->mmio->write_private(g->mmio->mem.ctx,0x10000000u+4*d[4],zero,80)||g->mmio->write_private(g->mmio->mem.ctx,0x10000000u+4*(next+64*i+16*slot),d,16)){*reason="inactive_descriptor_write_failed";return -1;}
    }
    g->mmio->mem.barrier(g->mmio->mem.ctx);words[6]=next;return 0;
}
