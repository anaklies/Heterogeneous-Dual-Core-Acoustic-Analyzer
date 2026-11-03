/* Transport fixture only: tagged constants and DONE publications, no DSP model. */
#include "gateway.h"
#include "mock_mmio.h"
#include "profile_upload.h"
#include "feature_runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct {sm_device old;uint32_t cursor[16],header[8];} fixture;
static fixture f;
static int rd(void*p,uint32_t a,uint32_t*v){fixture*x=p;
 if(a>=0x300&&a<0x340){*v=x->cursor[(a-0x300)/4];return 0;}
 if(a>=0x400&&a<0x420){*v=x->header[(a-0x400)/4];return 0;}
 return x->old.read(x->old.ctx,a,v);}
static int wr(void*p,uint32_t a,uint32_t v){fixture*x=p;return x->old.write(x->old.ctx,a,v);}
static void bar(void*p){fixture*x=p;x->old.barrier(x->old.ctx);}
static int store(void*p,uint32_t a,const uint32_t*w,uint32_t n){
 if(a<0x10200000u||(uint64_t)a+4ull*n>0x11000000u)return -1;
 memcpy((uint8_t*)p+a-0x10000000u,w,4*n);return 0;}
static int clean(void*p,uint32_t a,uint32_t n){(void)p;(void)a;(void)n;return 0;}
static void noop(void*p){(void)p;}
static void publication(uint32_t*mem,uint32_t at,uint32_t frame,uint64_t sample){
 uint32_t*d=mem+at,*h;unsigned i;
 if(at<524288||at+16>=4194304||d[0]!=0x414c5531u||d[7]<524304||d[7]+d[8]>=4194304)return;
 h=mem+d[7]-16;memset(h,0,64);h[0]=0x52534c54u;h[1]=frame;h[2]=d[11];h[3]=d[12];h[4]=d[14];h[5]=d[13];h[6]=frame;h[7]=(uint32_t)sample;h[8]=(uint32_t)(sample>>32);h[10]=d[8];h[11]=at;h[14]=1;
 /* Fixed fixture marker only; these words never establish numeric correctness. */
 for(i=0;i<d[8];i++)mem[d[7]+i]=0x3e800000u;
 mem[d[7]+30]=0x3f800000u; /* preparation-flow valid-impulse fixture tag */
}
static void inject(mock_mmio*m,gw*g,uint32_t frame,uint64_t*total){
 uint32_t r[32]={0},*mem=(uint32_t*)mock_mmio_ddr(m),cfg[32];unsigned i,c;
 memcpy(cfg,g->config_active_words,sizeof cfg);
 for(i=0;i<4096;i++){uint64_t sample=(*total)++;uint32_t*record=mem+(0x12000000u-0x10000000u)/4+(sample%65536)*8;
  for(c=0;c<6;c++)record[c]=(uint32_t)(int32_t)(-1000-(int)c);
  record[6]=(uint32_t)sample;record[7]=(uint32_t)(sample>>32);}
 f.cursor[0]=0x43555231u;f.cursor[1]=1;f.cursor[2]=0x12000000u;f.cursor[3]=2097152;f.cursor[4]=(uint32_t)(*total%65536)*32;f.cursor[5]=(uint32_t)*total;f.cursor[6]=(uint32_t)(*total>>32);f.cursor[7]=(uint32_t)(*total-1);f.cursor[11]=cfg[0];f.cursor[12]=cfg[1];f.cursor[13]=0x473b89c6;f.cursor[14]=1;f.cursor[15]=7;
 r[0]=3;r[1]=0x82000002u;r[2]=frame;r[3]=cfg[1];r[4]=cfg[0];r[6]=0x10100000u;r[8]=(uint32_t)*total;r[9]=(uint32_t)(*total>>32);r[11]=63;r[31]=0x473b89c6;
 f.header[0]=1;f.header[1]=frame;f.header[2]=cfg[1];f.header[3]=cfg[0];f.header[4]=r[8];f.header[5]=r[9];f.header[6]=0x100000;f.header[7]=1;
 for(c=0;c<6;c++)for(i=0;i<8;i++)mem[0x100000/4+c*8192+7171+i]=0x3e800000;
 for(i=0;i<=cfg[15]&&i<16;i++)publication(mem,cfg[6]+cfg[30]*i,frame,*total);
 if(cfg[8]&SM_P2_ENABLE)publication(mem,cfg[7],frame,*total);
 mock_mmio_set_result_words(m,r);
}
static int permission_probe(gw*g){
 int k,rc;gw_json_doc d;const char*error;char parse_error[128],*out=malloc(GW_LINE_BYTES);uint32_t before[32];
 if(!out)return -1;
 memcpy(before,g->config_active_words,sizeof before);
 for(k=0;k<2;k++){
  const char*text=k?"{\"featureId\":\"event_trigger\",\"params\":{}}":"{\"featureId\":\"cepstrum\",\"params\":{}}";
  gw_json_doc_init(&d);
  if(gw_json_parse(&d,text,strlen(text),32,1000,parse_error,sizeof parse_error)){free(out);return -1;}
  /* Only error paths are invoked in real-policy mode; no pl-live output is
   * returned. The MMIO source and network fixture remain test-fixture. */
  g->cfg.mock_fixture=0;g->cfg.allow_config_commit=k;g->cfg.allow_event_capture=0;
  rc=echo_features_dispatch(g,"feature.start",&d,gw_json_root(&d),out,GW_LINE_BYTES,&error);
  gw_json_doc_free(&d);g->cfg.mock_fixture=1;
  if(rc>=0||strcmp(error,"not_ready")||g->pending_config||echo_features_busy(g)||memcmp(before,g->config_active_words,sizeof before)){free(out);return -1;}
 }
 g->cfg.allow_config_commit=0;g->cfg.allow_event_capture=0;free(out);return 0;
}
int main(int argc,char**argv){
 mock_mmio*m;gw*g;gw_config cfg;gw_mmio*mm;FILE*image;char error[512];uint32_t words[32]={1,1,0x10000000,4194304,0x10000000,0x11000000,524288,0,9,0x12000000,0x1000000,0x12000000,0x14000000,0x13000000};uint64_t total=0;uint32_t frame=1;
 if(argc<4||argc>5){fprintf(stderr,"usage: fixture REGISTRY PROFILE.smi SPOOL [SERVICES.json]\n");return 2;}
 m=mock_mmio_create();g=calloc(1,sizeof *g);if(!m||!g)return 3;mm=mock_mmio_gw(m);
 image=fopen(argv[2],"rb");if(!image)return 4;
 {sm_upload_memory upload={mock_mmio_ddr(m),store,clean,noop,0x10000000,4194304};int rc=sm_upload_profile(image,&upload);fclose(image);if(rc){fprintf(stderr,"fixture upload %d\n",rc);return 5;}}
 words[7]=525312;words[15]=10;words[30]=64;
 if(sm_commit_config(&mm->dev,words)||sm_config_status(&mm->dev,1))return 6;
 f.old=mm->dev;mm->dev.ctx=&f;mm->dev.read=rd;mm->dev.write=wr;mm->dev.barrier=bar;
 gw_config_defaults(&cfg);cfg.mock_fixture=1;cfg.poll_ms=1;cfg.control_port=0;cfg.binary_port=0;
 snprintf(cfg.bind_addr,sizeof cfg.bind_addr,"127.0.0.1");snprintf(cfg.spool_dir,sizeof cfg.spool_dir,"%s",argv[3]);snprintf(cfg.feature_registry_file,sizeof cfg.feature_registry_file,"%s",argv[1]);
 snprintf(cfg.state_dir,sizeof cfg.state_dir,"%s/state",argv[3]);
 if(argc==5)snprintf(cfg.service_catalog_file,sizeof cfg.service_catalog_file,"%s",argv[4]);
 if(gw_init(g,&cfg,mm,error,sizeof error)){fprintf(stderr,"fixture init %s\n",error);return 7;}
 memcpy(g->config_active_words,words,128);g->config_active_known=1;g->active_config_version=1;
 inject(m,g,frame++,&total);gw_pump(g,0);
 if(permission_probe(g)){fprintf(stderr,"PERMISSION_PROBE_FAIL\n");return 8;}
 printf("{\"controlPort\":%u,\"binaryPort\":%u,\"sourceKind\":\"test-fixture\",\"numericDSPVerified\":false}\n",g->ctl_bound_port,g->bin_bound_port);fflush(stdout);
 while(!g->stop&&gw_clock_ms()-g->start_ms<60000){inject(m,g,frame++,&total);if(gw_pump(g,0)<0)break;}
 gw_shutdown(g);mock_mmio_destroy(m);free(g);return 0;
}
