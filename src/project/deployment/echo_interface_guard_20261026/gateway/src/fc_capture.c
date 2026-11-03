#include "fc_capture.h"
#include <string.h>
#include <math.h>
/* Pipeline bits 0..9 describe acquisition/memory/foreground failures.
 * Event, background and sensor status do not establish a PCM discontinuity. */
#define FC_DATA_FAULTS 0x3ffu
static uint64_t join(uint32_t a,uint32_t b){return a|((uint64_t)b<<32);}
static float asfloat(uint32_t a){float f;memcpy(&f,&a,4);return f;}
static int regs(gw*g,uint32_t at,uint32_t*w,unsigned n){
 unsigned i;sm_device*d=&g->mmio->dev;
 for(i=0;i<n;i++)if(d->read(d->ctx,at+4*i,w+i))return -1;
 d->barrier(d->ctx);return 0;
}
static int ready(gw*g){return g&&g->mmio&&g->mmio->dev.read&&g->mmio->dev.barrier&&g->mmio->mem.read&&g->mmio->mem.invalidate&&g->mmio->mem.barrier;}
static int copy(gw*,uint64_t,uint32_t*,uint32_t);
typedef struct {
 int valid;uint64_t requested_until,selected_ms;float peak;
 fc_provenance provenance;
 uint32_t amplitude[1025],power[1025],density[1025],levels[48];
} transient_frame;
static transient_frame held_frames[6];
void fc_transient_poll(gw*g){
 if(!ready(g)||!g->has_result||!g->config_active_known||g->now_ms-g->snap_rx_ms>300)return;
 for(unsigned ch=0;ch<6;ch++){
  transient_frame*c=&held_frames[ch];uint32_t best[8]={0},scratch[3075],levels[48],after[8];float strongest=-1;uint32_t bestbase=0;unsigned bestslot=0;
  if(g->now_ms>c->requested_until)continue;
  if(c->valid&&(c->provenance.session!=g->config_active_words[0]||c->provenance.config!=g->active_config_version))c->valid=0;
  for(unsigned slot=0;slot<4;slot++){
   uint32_t a[8],peak_word;uint64_t base;
   if(regs(g,0x400+slot*32,a,8)||a[0]!=1||a[7]!=1||a[2]!=g->active_config_version||a[3]!=g->config_active_words[0])continue;
   if(c->valid&&(int32_t)(a[1]-c->provenance.frame)<=0)continue;
   base=(uint64_t)g->config_active_words[2]+a[6];if(base>0xffffffffu)continue;
   if(copy(g,base+ch*32768u+7172u*4,&peak_word,1))continue;
   float peak=asfloat(peak_word);if(!isfinite(peak)||peak<0)continue;
   if(peak>strongest||(peak==strongest&&(int32_t)(a[1]-best[1])>0)){strongest=peak;memcpy(best,a,sizeof best);bestbase=(uint32_t)base;bestslot=slot;}
  }
  if(strongest<0||(c->valid&&g->now_ms-c->selected_ms<500&&strongest<=c->peak))continue;
  if(copy(g,(uint64_t)bestbase+ch*32768u+4096u*4,scratch,3075))continue;
  int failed=0;for(unsigned cc=0;cc<6;cc++)if(copy(g,(uint64_t)bestbase+cc*32768u+7171u*4,levels+cc*8,8)){failed=1;break;}
  if(failed||regs(g,0x400+bestslot*32,after,8)||memcmp(best,after,sizeof best))continue;
  for(unsigned k=0;k<1025;k++){c->amplitude[k]=scratch[k*3];c->density[k]=scratch[k*3+1];c->power[k]=scratch[k*3+2];}
  memcpy(c->levels,levels,sizeof levels);memset(&c->provenance,0,sizeof c->provenance);
  c->provenance.session=best[3];c->provenance.config=best[2];c->provenance.frame=best[1];c->provenance.first_sample=join(best[4],best[5]);
  c->provenance.last_sample=c->provenance.first_sample+2047;c->provenance.sample_rate=asfloat(g->snap.word[31]);c->provenance.gap=(g->snap.word[10]&FC_DATA_FAULTS)!=0;
  c->peak=strongest;c->selected_ms=g->now_ms;c->valid=1;
 }
}
int fc_transient_read(gw*g,const char*id,unsigned ch,uint32_t*data,uint32_t cap,uint32_t*words,fc_provenance*p){
 if(!ready(g)||ch>5||!data||!words||!p)return -1;
 held_frames[ch].requested_until=g->now_ms+2000;fc_transient_poll(g);transient_frame*c=&held_frames[ch];
 if(!c->valid||c->provenance.config!=g->active_config_version||c->provenance.session!=g->config_active_words[0]||g->now_ms-c->selected_ms>600)return -2;
 uint32_t n=(!strcmp(id,"levels_core")||!strcmp(id,"levels_extended"))?48:1025;if(cap<n)return -1;
 const uint32_t*src=n==48?c->levels:!strcmp(id,"fft")?c->amplitude:!strcmp(id,"power")?c->power:!strcmp(id,"stft")?c->density:NULL;
 if(!src)return -1;
 memcpy(data,src,n*4);*words=n;*p=c->provenance;p->frame_age_ms=(uint32_t)(g->now_ms-c->selected_ms);return 0;
}
static int copy(gw*g,uint64_t address,uint32_t*w,uint32_t n){
 sm_memory*m=&g->mmio->mem;
 if(address>0xffffffffu||address<m->reserved_low||address+4ull*n>m->reserved_high)return -1;
 if(m->invalidate(m->ctx,(uint32_t)address,n*4))return -1;
 m->barrier(m->ctx);
 if(m->read(m->ctx,(uint32_t)address,w,n))return -1;
 m->barrier(m->ctx);return 0;
}
int fc_live_frame(gw*g,unsigned ch,uint32_t last_frame,uint32_t last_config,uint32_t*out,fc_provenance*p){
 if(!ready(g)||!g->has_result||!g->config_active_known||ch>5||!out||!p)return -1;
 uint32_t chosen[8]={0},after[8];unsigned selected=0;int found=0;
 for(unsigned slot=0;slot<4;slot++){
  uint32_t a[8];if(regs(g,0x400+slot*32,a,8))return -1;
  if(a[0]!=1||a[7]!=1||a[2]!=g->active_config_version||a[3]!=g->config_active_words[0])continue;
  if(last_config==a[2]&&last_frame&&(int32_t)(a[1]-last_frame)<=0)continue;
  int newer_start=last_config!=a[2]||!last_frame;
  if(!found||(newer_start?(int32_t)(a[1]-chosen[1])>0:(int32_t)(a[1]-chosen[1])<0)){memcpy(chosen,a,sizeof chosen);selected=slot;found=1;}
 }
 if(!found)return -2;
 uint64_t base=(uint64_t)g->config_active_words[2]+chosen[6];
 if(copy(g,base+ch*32768u+4096u*4,out+16,3075))return -1;
 for(unsigned c=0;c<6;c++)if(copy(g,base+c*32768u+7171u*4,out+16+3075+c*8,8))return -1;
 if(copy(g,(uint64_t)g->config_active_words[2]+selected*65536u,out+16+3075+48,12288))return -1;
 if(regs(g,0x400+selected*32,after,8)||memcmp(chosen,after,sizeof chosen))return -2;
 memset(out,0,64);out[0]=0x3154464cu;out[1]=1;out[2]=chosen[1];out[3]=chosen[2];out[4]=chosen[3];out[5]=ch;
 out[6]=g->snap.word[31];out[7]=2048;out[8]=chosen[4];out[9]=chosen[5];out[10]=1025;out[11]=3075;out[12]=48;out[13]=12288;
 out[14]=(last_config==chosen[2]&&last_frame&&chosen[1]!=last_frame+1u)?1u:0u;
 memset(p,0,sizeof *p);p->session=chosen[3];p->config=chosen[2];p->frame=chosen[1];p->first_sample=join(chosen[4],chosen[5]);p->last_sample=p->first_sample+2047;p->sample_rate=asfloat(out[6]);p->gap=(int)out[14];return 0;
}
int fc_p0_read(gw*g,const char*id,unsigned ch,uint32_t*data,uint32_t cap,uint32_t*words,fc_provenance*p){
 uint32_t a[8],b[8],scratch[3075],slot,need=0,i,c,kind,base;unsigned attempt;
 if(words)*words=0;
 if(!ready(g)||!id||!data||!words||!p||ch>5)return -1;
 memset(p,0,sizeof *p);
 if(!g->has_result||!g->config_active_known)return -2;
 slot=g->snap.word[SM_R_SLOT];if(slot>3)return -2;
 if(!strcmp(id,"io_pcm")){kind=0;need=12288;}
 else if(!strcmp(id,"levels_core")||!strcmp(id,"levels_extended")){kind=1;need=48;}
 else if(!strcmp(id,"fft")){kind=2;need=1025;}
 else if(!strcmp(id,"power")){kind=5;need=1025;}
 else if(!strcmp(id,"stft")){kind=3;need=1025;}
 else if(!strcmp(id,"signal_quality")||!strcmp(id,"data_continuity")){kind=4;need=32;}
 else return -1;
 if(cap<need)return -1;
 for(attempt=0;attempt<3;attempt++){
  if(regs(g,0x400+slot*32,a,8))return -1;
  if(a[0]!=1||a[7]!=1||a[1]!=g->snap.word[2]||a[2]!=g->snap.word[3]||a[3]!=g->snap.word[4]||a[4]!=g->snap.word[8]||a[5]!=g->snap.word[9])continue;
  if(a[2]!=g->config_active_words[SM_C_VERSION]||a[3]!=g->config_active_words[SM_C_SESSION])continue;
  if((uint64_t)g->config_active_words[SM_C_ARENA_BASE]+a[6]>0xffffffffu)return -1;
  base=g->config_active_words[SM_C_ARENA_BASE]+a[6];
  if(base!=g->snap.word[SM_R_FFT_BASE])continue;
  if(kind==0){if(copy(g,(uint64_t)g->config_active_words[SM_C_ARENA_BASE]+slot*65536u,data,need))return -1;}
  else if(kind==1){for(c=0;c<6;c++)if(copy(g,(uint64_t)base+c*32768u+7171u*4,data+c*8,8))return -1;}
  else if(kind==2||kind==3||kind==5){
   if(copy(g,(uint64_t)base+ch*32768u+4096u*4,scratch,3075))return -1;
   for(i=0;i<1025;i++)data[i]=scratch[3*i+(kind==5?2:(kind==3))];
  }else memcpy(data,g->snap.word,128);
  if(regs(g,0x400+slot*32,b,8))return -1;
  if(memcmp(a,b,sizeof a))continue;
  p->frame=a[1];p->config=a[2];p->session=a[3];p->first_sample=join(a[4],a[5]);
  if(p->first_sample>UINT64_MAX-2047)return -2;
  p->last_sample=p->first_sample+2047;p->sample_rate=asfloat(g->snap.word[31]);
  p->gap=(g->snap.word[SM_R_FAULTS]&FC_DATA_FAULTS)!=0;
  *words=need;return 0;
 }return -2;
}
static int cursor(gw*g,uint32_t*w){
 uint32_t b[16];
 if(regs(g,0x300,w,16)||regs(g,0x300,b,16))return -1;
 if(memcmp(w,b,sizeof b))return -2;
 if(w[0]!=0x43555231u||w[14]!=1||!(w[15]&1)||w[15]&32||w[3]<4096||(w[3]&(w[3]-1))||w[4]>=w[3]||w[4]%32)return -2;
 if(((join(w[5],w[6])%(w[3]/32))*32)!=w[4])return -2;
 return 0;
}
static int broken(fc_raw_reader*r,fc_provenance*p){r->gap=1;p->gap=1;return -2;}
int fc_raw_poll(gw*g,fc_raw_reader*r,uint32_t*data,uint32_t cap,uint32_t*count,fc_provenance*p){
 uint32_t a[16],b[16],tail[8],n,start,n1,i,capacity;uint64_t total,after,first,last;int rc;unsigned attempt;
 if(count)*count=0;
 if(!ready(g)||!r||!data||!cap||!count||!p)return -1;
 memset(p,0,sizeof *p);if(r->gap)return broken(r,p);
 if(cap>4096)cap=4096;
 for(attempt=0;attempt<3;attempt++){
  rc=cursor(g,a);if(rc==-1)return -1;if(rc)continue;
  total=join(a[5],a[6]);capacity=a[3]/32;
  if(!r->initialized){
   if(!total)return -2;
   if(a[10]&FC_DATA_FAULTS)return broken(r,p);
   /* Anchor the requested sequence in committed payload, not the acquisition
    * timestamp telemetry. No record is returned by this initialization read. */
   start=a[4]?a[4]-32:a[3]-32;
   if(copy(g,(uint64_t)a[2]+start,tail,8))return -1;
   rc=cursor(g,b);if(rc==-1)return -1;if(rc)continue;
   /* The producer must advance while PCM is being copied. Requiring the
    * entire live cursor to freeze across DDR access starves initialization.
    * The anchor remains immutable until one ring capacity has elapsed. */
   after=join(b[5],b[6]);
   if(a[1]!=b[1]||a[2]!=b[2]||a[3]!=b[3]||a[11]!=b[11]||a[12]!=b[12]||a[13]!=b[13]||a[9]!=b[9]||(b[10]&FC_DATA_FAULTS)||after<total||after-total>=capacity)continue;
   r->generation=a[1];r->base=a[2];r->bytes=a[3];r->session=a[11];r->config=a[12];r->rate=a[13];r->dropped=a[9];
   r->next_record=total;r->next_sample=join(tail[6],tail[7])+1;r->initialized=1;
   if(!r->next_sample)return broken(r,p);
   return -2;
  }
  if(a[1]!=r->generation||a[2]!=r->base||a[3]!=r->bytes||a[11]!=r->session||a[12]!=r->config||a[13]!=r->rate||a[9]!=r->dropped||(a[10]&FC_DATA_FAULTS)||total<r->next_record||total-r->next_record>=capacity)return broken(r,p);
  if(total==r->next_record)return -2;
  n=(uint32_t)((total-r->next_record)>cap?cap:(total-r->next_record));
  start=(uint32_t)(r->next_record%capacity);n1=capacity-start;if(n1>n)n1=n;
  if(copy(g,(uint64_t)a[2]+start*32u,data,n1*8))return -1;
  if(n>n1&&copy(g,a[2],data+n1*8,(n-n1)*8))return -1;
  rc=cursor(g,b);if(rc==-1)return -1;if(rc)continue;
  after=join(b[5],b[6]);
  if(a[1]!=b[1]||a[2]!=b[2]||a[3]!=b[3]||a[11]!=b[11]||a[12]!=b[12]||a[13]!=b[13]||a[9]!=b[9]||(b[10]&FC_DATA_FAULTS)||after<total||after-r->next_record>=capacity)return broken(r,p);
  first=join(data[6],data[7]);last=first;
  if(first!=r->next_sample)return broken(r,p);
  for(i=1;i<n;i++){uint64_t v=join(data[i*8+6],data[i*8+7]);if(last==UINT64_MAX||v!=last+1)return broken(r,p);last=v;}
  if(last==UINT64_MAX)return broken(r,p);
  p->session=r->session;p->config=r->config;p->first_sample=first;p->last_sample=last;p->sample_rate=asfloat(r->rate);
  r->next_record+=n;r->next_sample=last+1;*count=n;return 0;
 }return -2;
}
