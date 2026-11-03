#include "sixmic_host.h"
#include <string.h>
static int valid(const sm_device *d) { return d && d->read && d->write && d->barrier; }
static int rd(const sm_device *d,uint32_t o,uint32_t *v) { return d->read(d->ctx,o,v)?SM_IO:SM_OK; }
static int wr(const sm_device *d,uint32_t o,uint32_t v) { return d->write(d->ctx,o,v)?SM_IO:SM_OK; }
uint64_t sm_join_u64(uint32_t low,uint32_t high) { return ((uint64_t)high<<32)|low; }
float sm_word_float(uint32_t word) { float f; memcpy(&f,&word,sizeof f); return f; }
int sm_identify(const sm_device *d,sm_identity *id) {
 uint32_t magic,lo,hi;
 if(!valid(d)||!id)return SM_ARGUMENT;
 if(rd(d,0,&magic)||rd(d,4,&id->protocol)||rd(d,8,&id->firmware)||rd(d,12,&lo)||rd(d,16,&hi))return SM_IO;
 if(magic!=0x534d4132u||id->protocol!=3)return SM_PROTOCOL;
 id->capabilities=sm_join_u64(lo,hi);return SM_OK;
}
int sm_read_snapshot(const sm_device *d,sm_snapshot *out,unsigned attempts) {
 sm_snapshot tmp;uint32_t after;unsigned n,i;
 if(!valid(d)||!out||!attempts)return SM_ARGUMENT;
 for(n=0;n<attempts;n++) {
  if(rd(d,0x18,&tmp.epoch))return SM_IO;
  if(tmp.epoch==0)return SM_NO_DATA;
  d->barrier(d->ctx);
  for(i=0;i<32;i++)if(rd(d,0x100+4*i,&tmp.word[i]))return SM_IO;
  d->barrier(d->ctx);
  if(rd(d,0x18,&after))return SM_IO;
  if(tmp.epoch==after) {
   if(tmp.word[0]!=3)return SM_PROTOCOL;
   *out=tmp;return SM_OK;
  }
 }
 return SM_RETRY;
}
int sm_commit_config(const sm_device *d,const uint32_t words[32]) {
 uint32_t state,active;unsigned i;
 if(!valid(d)||!words)return SM_ARGUMENT;
 if(rd(d,0x20,&state))return SM_IO;
 if(state&1)return SM_BUSY;
 if(rd(d,0x1c,&active))return SM_IO;
 /* Unique version makes completion distinguishable from a rejected request. */
 if(active==words[SM_C_VERSION])return SM_ARGUMENT;
 for(i=0;i<32;i++)if(wr(d,0x40+4*i,words[i]))return SM_IO;
 d->barrier(d->ctx);
 /* Only this write latches the complete 32-word shadow. An AXI error is failure. */
 if(wr(d,0x20,1))return SM_IO;
 d->barrier(d->ctx);return SM_OK;
}
int sm_config_status(const sm_device *d,uint32_t version) {
 uint32_t state,active;
 if(!valid(d))return SM_ARGUMENT;
 if(rd(d,0x20,&state))return SM_IO;
 if(state&1)return SM_BUSY;
 if(!(state&4))return SM_NO_DATA;
 d->barrier(d->ctx);
 if(rd(d,0x1c,&active))return SM_IO;
 return active==version?SM_OK:SM_REJECTED;
}
int sm_read_clip(const sm_device *d,unsigned bank,sm_clip *out) {
 sm_clip tmp;uint32_t mask,id;unsigned i;
 if(!valid(d)||!out||bank>1)return SM_ARGUMENT;
 if(rd(d,0x30,&mask))return SM_IO;
 if(!(mask&(1u<<bank)))return SM_NO_DATA;
 tmp.bank=bank;d->barrier(d->ctx);
 for(i=0;i<16;i++)if(rd(d,0x200+bank*0x40+4*i,&tmp.word[i]))return SM_IO;
 d->barrier(d->ctx);
 if(rd(d,0x30,&mask)||rd(d,0x200+bank*0x40,&id))return SM_IO;
 if(!(mask&(1u<<bank))||id!=tmp.word[0])return SM_RETRY;
 *out=tmp;return SM_OK;
}
int sm_release_clip(const sm_device *d,const sm_clip *clip) {
 uint32_t mask,id;
 if(!valid(d)||!clip||clip->bank>1)return SM_ARGUMENT;
 if(rd(d,0x30,&mask)||rd(d,0x200+clip->bank*0x40,&id))return SM_IO;
 if(!(mask&(1u<<clip->bank)))return SM_NO_DATA;
 if(id!=clip->word[0])return SM_RETRY;
 d->barrier(d->ctx);
 if(wr(d,0x2c,id))return SM_IO;
 d->barrier(d->ctx);
 if(wr(d,0x28,1u|(clip->bank<<1)))return SM_IO;
 d->barrier(d->ctx);return SM_OK;
}
int sm_clear_irq(const sm_device *d,uint32_t mask) {
 if(!valid(d)||!mask||(mask&~7u))return SM_ARGUMENT;
 if(wr(d,0x24,mask))return SM_IO;
 d->barrier(d->ctx);return SM_OK;
}
