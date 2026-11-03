#include "fc_capture.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef struct {uint32_t cursor[16],header[8];int flip,io,reads,advance;uint64_t corrupt;} fake;
static void barrier(void*p){(void)p;}
static int reg(void*p,uint32_t a,uint32_t*v){fake*f=p;if(f->io)return -1;
 if(a>=0x300&&a<0x340)*v=f->cursor[(a-0x300)/4];
 else if(a>=0x400&&a<0x420)*v=f->header[(a-0x400)/4];else return -1;
 return 0;}
static int inv(void*p,uint32_t a,uint32_t n){(void)p;(void)a;(void)n;return 0;}
static int mem(void*p,uint32_t a,uint32_t*d,uint32_t n){fake*f=p;uint32_t i;
 f->reads++;if(f->io)return -1;
 for(i=0;i<n;i++){
  uint32_t at=(a-0x100000u)/4+i;
  if(a<0x200000u){uint64_t index=at/8,sample;
   if(index<f->cursor[5])index+=((f->cursor[5]-1-index)/128)*128;
   sample=index+1000;d[i]=(at%8==6)?(uint32_t)sample:(at%8==7)?0:0xff800001u;if(sample==f->corrupt&&at%8==6)d[i]++;}
  else d[i]=at;
 }
 if(f->advance){f->cursor[5]++;f->cursor[4]=(f->cursor[5]%128)*32;f->cursor[7]++;}
 if(f->flip)f->header[1]++;
 return 0;
}
static gw g;static gw_mmio mm;
static void init(fake*f){memset(f,0,sizeof *f);memset(&g,0,sizeof g);memset(&mm,0,sizeof mm);
 mm.dev.ctx=f;mm.dev.read=reg;mm.dev.barrier=barrier;
 mm.mem.ctx=f;mm.mem.read=mem;mm.mem.invalidate=inv;mm.mem.barrier=barrier;mm.mem.reserved_low=0x100000;mm.mem.reserved_high=0x1100000;g.mmio=&mm;
 f->cursor[0]=0x43555231;f->cursor[1]=1;f->cursor[2]=0x100000;f->cursor[3]=4096;f->cursor[11]=3;f->cursor[12]=7;f->cursor[13]=0x473b89c6;f->cursor[14]=1;f->cursor[15]=7;
 g.has_result=1;g.config_active_known=1;g.config_active_words[0]=3;g.config_active_words[1]=7;g.config_active_words[2]=0x100000;
 f->header[0]=1;f->header[1]=5;f->header[2]=7;f->header[3]=3;f->header[4]=100;f->header[6]=0x100000;f->header[7]=1;
 g.snap.word[2]=5;g.snap.word[3]=7;g.snap.word[4]=3;g.snap.word[6]=0x200000;g.snap.word[8]=100;g.snap.word[31]=0x473b89c6;
}
static void total(fake*f,uint32_t n){f->cursor[4]=(n%128)*32;f->cursor[5]=n;f->cursor[7]=999+n;}
int main(void){fake f;fc_raw_reader r;fc_provenance p;uint32_t d[12288],n;
 init(&f);assert(fc_p0_read(&g,"fft",2,d,12288,&n,&p)==0&&n==1025&&p.frame==5&&p.last_sample==2147);
 assert(d[1]-d[0]==3);assert(fc_p0_read(&g,"stft",0,d,12288,&n,&p)==0&&d[0]==(0x100000u/4+4097));
 assert(fc_p0_read(&g,"levels_extended",0,d,12288,&n,&p)==0&&n==48&&d[8]-d[0]==8192);
 assert(fc_p0_read(&g,"io_pcm",0,d,12288,&n,&p)==0&&n==12288);
 assert(fc_p0_read(&g,"signal_quality",0,d,12288,&n,&p)==0&&n==32&&d[2]==5);
 g.snap.word[SM_R_FAULTS]=(1u<<23)|(1u<<14);g.snap.word[SM_R_HANDOFF_DROPS]=19;
 assert(fc_p0_read(&g,"fft",0,d,12288,&n,&p)==0&&!p.gap);
 f.flip=1;f.reads=0;assert(fc_p0_read(&g,"fft",0,d,12288,&n,&p)==-2&&n==0&&f.reads<=3);
 init(&f);memset(&r,0,sizeof r);total(&f,2);f.cursor[7]+=50;f.cursor[10]=1u<<14;
 assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2&&r.initialized&&r.next_sample==1002&&!r.gap);
 total(&f,5);f.cursor[7]+=51;assert(fc_raw_poll(&g,&r,d,4,&n,&p)==0&&n==3&&p.first_sample==1002&&p.last_sample==1004&&d[0]==0xff800001u);
 total(&f,7);f.corrupt=1006;assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2&&n==0&&p.gap&&r.next_record==5);
 init(&f);memset(&r,0,sizeof r);total(&f,126);assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2);total(&f,130);
 assert(fc_raw_poll(&g,&r,d,4,&n,&p)==0&&!p.gap&&f.reads==3&&n==4&&p.first_sample==1126&&p.last_sample==1129);
 init(&f);memset(&r,0,sizeof r);total(&f,2);assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2);f.cursor[1]++;assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2&&p.gap&&!n);
 init(&f);memset(&r,0,sizeof r);total(&f,2);assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2);total(&f,130);assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2&&p.gap&&!n);
 init(&f);memset(&r,0,sizeof r);total(&f,2);assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2);f.cursor[10]=1u;assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2&&p.gap&&!n);
 init(&f);memset(&r,0,sizeof r);total(&f,2);assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2);f.cursor[9]++;assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2&&p.gap&&!n);
 init(&f);memset(&r,0,sizeof r);total(&f,2);f.advance=1;
 assert(fc_raw_poll(&g,&r,d,4,&n,&p)==-2&&r.initialized&&r.next_record==2&&r.next_sample==1002);
 f.advance=0;assert(fc_raw_poll(&g,&r,d,4,&n,&p)==0&&n==1&&p.first_sample==1002&&!p.gap);
 puts("FC_CAPTURE_PASS snapshot_coherence selectors raw_sequence gap transition overrun");return 0;
}
