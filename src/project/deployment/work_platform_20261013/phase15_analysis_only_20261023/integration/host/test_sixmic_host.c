#include "sixmic_host.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef struct {
 uint32_t reg[0x280/4],latched[32];unsigned writes,barriers;
 int mutate,fail_read,fail_write;
} fake;
static int read32(void *ctx,uint32_t o,uint32_t *v) {
 fake *f=ctx;if(f->fail_read)return -1;
 assert(o<sizeof f->reg&&!(o&3));
 if(o==0x140&&f->mutate) {
  unsigned i;f->reg[0x18/4]++;for(i=0;i<32;i++)f->reg[0x100/4+i]=200+i;
  f->reg[0x100/4]=3;f->mutate=0;
 }
 *v=f->reg[o/4];return 0;
}
static int write32(void *ctx,uint32_t o,uint32_t v) {
 fake *f=ctx;unsigned bank;if(f->fail_write)return -1;
 assert(o<sizeof f->reg&&!(o&3));f->writes++;
 if(o==0x20) {if(f->reg[o/4]&1)return -1;memcpy(f->latched,f->reg+0x40/4,sizeof f->latched);f->reg[o/4]=1;}
 else if(o==0x28) {bank=(v>>1)&1;if(!(f->reg[0x30/4]&(1u<<bank))||f->reg[(0x200+0x40*bank)/4]!=f->reg[0x2c/4])return -1;f->reg[0x30/4]&=~(1u<<bank);}
 else if(o==0x24) {f->reg[0x20/4]&=~((v&3u)<<1);if(v&4)f->reg[0x14/4]=0;}
 else f->reg[o/4]=v;
 return 0;
}
static void barrier(void *ctx) {((fake *)ctx)->barriers++;}
int main(void) {
 fake f;sm_identity id;sm_snapshot s;sm_clip clip;uint32_t cfg[32];unsigned i,n;
 sm_device d={&f,read32,write32,barrier};memset(&f,0,sizeof f);
 f.reg[0]=0x534d4132;f.reg[1]=3;f.reg[2]=0x82000001;
 assert(sm_identify(&d,&id)==SM_OK&&id.protocol==3&&id.capabilities==0);
 f.reg[1]=2;assert(sm_identify(&d,&id)==SM_PROTOCOL);f.reg[1]=3;
 assert(sm_read_snapshot(&d,&s,2)==SM_NO_DATA);
 f.reg[0x18/4]=1;for(i=0;i<32;i++)f.reg[0x100/4+i]=100+i;f.reg[0x100/4]=3;
 f.mutate=1;assert(sm_read_snapshot(&d,&s,1)==SM_RETRY);
 assert(sm_read_snapshot(&d,&s,2)==SM_OK&&s.epoch==2&&s.word[31]==231);
 f.mutate=1;assert(sm_read_snapshot(&d,&s,2)==SM_OK&&s.epoch==3&&s.word[1]==201);
 for(i=0;i<32;i++)cfg[i]=i+1000;
 cfg[SM_C_VERSION]=19;
 f.reg[0x20/4]=1;n=f.writes;assert(sm_commit_config(&d,cfg)==SM_BUSY&&n==f.writes);
 f.reg[0x20/4]=0;assert(sm_commit_config(&d,cfg)==SM_OK&&f.writes==n+33);
 assert(!memcmp(cfg,f.latched,sizeof cfg)&&sm_config_status(&d,19)==SM_BUSY);
 f.reg[0x20/4]=4;f.reg[0x1c/4]=19;assert(sm_config_status(&d,19)==SM_OK);
 assert(sm_commit_config(&d,cfg)==SM_ARGUMENT);assert(sm_config_status(&d,20)==SM_REJECTED);
 assert(sm_read_clip(&d,0,&clip)==SM_NO_DATA);
 f.reg[0x30/4]=3;for(i=0;i<16;i++){f.reg[0x200/4+i]=50+i;f.reg[0x240/4+i]=90+i;}
 assert(sm_read_clip(&d,1,&clip)==SM_OK&&clip.bank==1&&clip.word[15]==105);
 clip.word[0]++;n=f.writes;assert(sm_release_clip(&d,&clip)==SM_RETRY&&f.writes==n);
 clip.word[0]--;assert(sm_release_clip(&d,&clip)==SM_OK&&f.reg[0x30/4]==1);
 assert(sm_release_clip(&d,&clip)==SM_NO_DATA);
 assert(sm_read_clip(&d,0,&clip)==SM_OK&&clip.word[0]==50);
 assert(sm_release_clip(&d,&clip)==SM_OK&&f.reg[0x30/4]==0);
 f.fail_read=1;assert(sm_identify(&d,&id)==SM_IO);f.fail_read=0;
 f.fail_write=1;assert(sm_clear_irq(&d,1)==SM_IO);f.fail_write=0;
 assert(sm_clear_irq(&d,8)==SM_ARGUMENT&&sm_clear_irq(&d,3)==SM_OK);
 assert(sm_word_float(0x3f800000)==1.0f&&sm_join_u64(1,2)==0x200000001ull);
 assert(f.barriers>10);puts("HOST_API_PASS protocol=3 snapshot_retry config32 clip2 ID_release IO_errors");return 0;
}
