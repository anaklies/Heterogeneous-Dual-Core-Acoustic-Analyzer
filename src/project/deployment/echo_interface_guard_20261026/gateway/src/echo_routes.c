#include "gateway.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int echo_routes_load(gw *g,const char *path,char *error,size_t capacity){
    FILE *f;long size;char *text;gw_json_doc doc;const gw_json_node *root,*routes,*item;unsigned i=0;int rc=-1;
    if(!path||!path[0])return 0;
    f=fopen(path,"rb");if(!f)return -1;
    if(fseek(f,0,SEEK_END)||(size=ftell(f))<=0||size>65536||fseek(f,0,SEEK_SET)){fclose(f);return -1;}
    text=(char*)malloc((size_t)size+1);if(!text){fclose(f);return -1;}
    if(fread(text,1,(size_t)size,f)!=(size_t)size){free(text);fclose(f);return -1;}fclose(f);text[size]=0;
    gw_json_doc_init(&doc);
    if(gw_json_parse(&doc,text,(size_t)size,16,4096,error,capacity))goto done;
    root=gw_json_root(&doc);routes=gw_json_obj_get(&doc,root,"routes");
    if(!routes||routes->type!=GW_JSON_ARRAY||!gw_json_arr_count(routes)||gw_json_arr_count(routes)>GW_SERVICE_ROUTES)goto done;
    for(item=routes->child;item;item=item->next,i++){
        uint32_t a,n,d,v;
        if(gw_json_get_u32(&doc,item,"address",&a)||gw_json_get_u32(&doc,item,"words",&n)||gw_json_get_u32(&doc,item,"descriptor",&d)||gw_json_get_u32(&doc,item,"generation",&v))goto done;
        if(!n||n>GW_SERVICE_MAX_WORDS||!v||(a&3)||a<0x10200040u||(uint64_t)a+4ull*n>0x11000000ull||(d&15)||d<524288u||d>=4194304u)goto done;
        g->service_routes[i].address=a;g->service_routes[i].words=n;g->service_routes[i].descriptor=d;g->service_routes[i].generation=v;g->service_routes[i].seen=0;
        if(gw_json_get_str(&doc,item,"name",g->service_routes[i].name,sizeof g->service_routes[i].name,NULL))goto done;
        (void)gw_json_get_str(&doc,item,"units",g->service_routes[i].units,sizeof g->service_routes[i].units,NULL);
    }
    g->service_route_count=i;rc=0;
done:
    if(rc){g->service_route_count=0;if(capacity)snprintf(error,capacity,"invalid bounded service catalog");}
    gw_json_doc_free(&doc);free(text);return rc;
}

int echo_service_read(gw *g,uint8_t *payload,uint32_t *bytes){
    static uint32_t data[GW_SERVICE_MAX_WORDS];sm_service_result header;uint32_t hint[16],a,n,limit;unsigned route=0,i;int rc;
    if(!g||!g->has_result||!g->mmio||!g->mmio->mem.read)return -1;
    if(g->route_session!=g->snap.word[SM_R_SESSION]||g->route_config!=g->snap.word[SM_R_CONFIG]){
        for(i=0;i<g->service_route_count;i++)g->service_routes[i].seen=0;
        g->route_session=g->snap.word[SM_R_SESSION];g->route_config=g->snap.word[SM_R_CONFIG];
    }
    if(g->service_route_count){route=g->service_route_next++%g->service_route_count;a=g->service_routes[route].address;limit=g->service_routes[route].words;}
    else {a=g->cfg.service_snapshot_addr;limit=g->cfg.service_snapshot_words;}
    if(a<64||limit>GW_SERVICE_MAX_WORDS||!limit)return -1;
    if(g->mmio->mem.invalidate(g->mmio->mem.ctx,a-64,64))return -1;
    g->mmio->mem.barrier(g->mmio->mem.ctx);
    if(g->mmio->mem.read(g->mmio->mem.ctx,a-64,hint,16)||hint[0]!=0x52534c54u)return -2;
    n=hint[10];if(!n||n>limit||n>GW_SERVICE_MAX_WORDS)return -2; /* Never silently truncate. */
    rc=sm_copy_service(&g->mmio->mem,a,n,g->snap.word[SM_R_SESSION],g->snap.word[SM_R_CONFIG],data,&header,2);
    if(rc){if(rc==SM_RETRY)g->stats.service_snapshot_retries++;else g->stats.service_snapshot_errors++;return rc;}
    if(memcmp(hint,header.word,sizeof hint)){g->stats.service_snapshot_retries++;return SM_RETRY;}
    if(header.word[10]!=n||header.word[15])return -2;
    if(g->service_route_count){
        uint32_t d=header.word[11],base=g->service_routes[route].descriptor;
        if(g->config_active_known&&base>=524288u&&base<525312u)base=g->config_active_words[6]+(base-524288u);
        if(n!=limit||header.word[4]!=g->service_routes[route].generation||header.word[5]!=1||d<base||d>=base+64u||((d-base)&15u))return -2;
        if(g->service_routes[route].seen&&header.word[1]==g->service_routes[route].sequence)return SM_NO_DATA;
        g->service_routes[route].seen=1;g->service_routes[route].sequence=header.word[1];
    }
    for(i=0;i<16;i++)sma_put_u32(payload+i*4,header.word[i]);
    for(i=0;i<n;i++)sma_put_u32(payload+64+i*4,data[i]);
    *bytes=64+n*4;g->stats.service_snapshots_ok++;return 0;
}
