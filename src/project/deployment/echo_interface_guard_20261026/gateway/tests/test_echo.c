#include "fake_mmio.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned checks;
#define CHECK(v) do {checks++;if(!(v)){fprintf(stderr,"ECHO_TEST_FAIL line=%d\n",__LINE__);return 1;}}while(0)
static int failed_read(void*c,uint32_t a,uint32_t*b,uint32_t n){(void)c;(void)a;(void)b;(void)n;return -1;}
int main(int argc,char**argv){
    fake_env env;gw*g;uint32_t header[16],result[32],cfg[32],clip[16],bytes;static uint32_t data[11276];static uint8_t packet[65536];unsigned i;
    CHECK(argc==2);CHECK(fake_env_start(&env,argv[1])==0);g=env.gateway;
    fake_fill_result_words(result,99,3,1,1000);memcpy(g->snap.word,result,sizeof result);g->has_result=1;
    g->service_route_count=3;
    for(i=0;i<3;i++){g->service_routes[i].address=0x10200000u+i*0x10000u;g->service_routes[i].words=i==0?1025:i==1?28:11276;g->service_routes[i].descriptor=524288+64*i;g->service_routes[i].generation=1;}
    for(i=0;i<11276;i++)data[i]=0x3f000000u+i;
    for(i=0;i<3;i++){
        fake_fill_service_header(header,1,3,g->service_routes[i].words,1);header[11]=g->service_routes[i].descriptor;
        mock_mmio_set_service(env.mmio,g->service_routes[i].address,header,data,g->service_routes[i].words);
    }
    for(i=0;i<3;i++){CHECK(echo_service_read(g,packet,&bytes)==0);CHECK(bytes==64+4*g->service_routes[i].words);CHECK(sma_get_u32(packet+bytes-4)==data[g->service_routes[i].words-1]);}
    CHECK(echo_service_read(g,packet,&bytes)==SM_NO_DATA);
    g->service_route_next=0;fake_fill_service_header(header,1,3,1025,1);header[11]=524288;header[4]=2;
    mock_mmio_set_service(env.mmio,0x10200000,header,data,1025);CHECK(echo_service_read(g,packet,&bytes)!=0);
    g->service_route_next=0;header[4]=1;header[10]=1026;mock_mmio_set_service(env.mmio,0x10200000,header,data,1026);CHECK(echo_service_read(g,packet,&bytes)!=0);
    fake_fill_config(cfg,1,3);memcpy(g->config_active_words,cfg,sizeof cfg);g->config_active_known=1;
    fake_fill_clip_words(clip,44,0x12000000,4,1000,1,3);{uint8_t records[128];fake_make_records(records,4,1000);CHECK(mock_mmio_inject_clip(env.mmio,0,clip,records,sizeof records)==0);}
    {sm_memory_read original=g->mmio->mem.read;g->mmio->mem.read=failed_read;sm_clip item;item.bank=0;memcpy(item.word,clip,sizeof clip);
     CHECK(gw_event_capture_bank(g,0,&item)!=0);CHECK(mock_mmio_clip_released_count(env.mmio)==0);CHECK(g->event_retry_after[0]>g->now_ms);g->mmio->mem.read=original;}
    {uint32_t *memory=(uint32_t*)mock_mmio_ddr(env.mmio),next_cfg[32];const char*reason="";unsigned row,slot;
     cfg[6]=524288;cfg[30]=64;cfg[8]=9;cfg[15]=2;g->active_config_version=3;
     memcpy(g->config_active_words,cfg,sizeof cfg);
     for(row=0;row<3;row++)for(slot=0;slot<4;slot++){
        uint32_t*d=memory+524288+64*row+16*slot;memset(d,0,64);d[0]=0x414c5531u;d[2]=600128+24576*row;d[3]=25;d[4]=604352+24576*row+80*slot;d[7]=608192+24576*row;d[8]=1025;d[11]=1;d[12]=3;d[14]=1;
     }
     memcpy(next_cfg,cfg,sizeof cfg);next_cfg[1]=4;next_cfg[14]=1;
     CHECK(echo_prepare_config(g,next_cfg,&reason)==0);CHECK(next_cfg[6]==528384);CHECK(memory[524288+12]==3);CHECK(memory[528384+12]==4);CHECK(memory[528384+4]==532480);
     memcpy(g->config_active_words,next_cfg,sizeof next_cfg);g->active_config_version=4;next_cfg[1]=5;next_cfg[14]=0;
     CHECK(echo_prepare_config(g,next_cfg,&reason)==0);CHECK(next_cfg[6]==524288);CHECK(memory[528384+12]==4);CHECK(memory[524288+12]==5);CHECK(memory[524288+4]==540672);
     CHECK(g->mmio->write_private(g->mmio->mem.ctx,0x10000000,(const uint32_t*)packet,16)!=0);
    }
    fake_env_stop(&env);printf("ECHO_GATEWAY_TEST_PASS checks=%u full1025=1 full11276=1 noTruncation=1 retainedOnIOFailure=1\n",checks);return 0;
}
