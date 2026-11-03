#include "fft_snapshot.h"
#include <string.h>
static int header(const sm_device*d,unsigned slot,uint32_t*h){unsigned i;for(i=0;i<8;i++)if(d->read(d->ctx,0x400+slot*32+i*4,&h[i]))return SM_IO;d->barrier(d->ctx);return SM_OK;}
int sm_copy_fft_snapshot(const sm_device*d,const sm_memory*m,const sm_snapshot*expected,uint32_t channels,uint32_t*data,uint32_t capacity_words){
 uint32_t before[8],after[8],slot,base,n=0,at=0,ch;
 if(!d||!d->read||!d->barrier||!m||!m->read||!m->invalidate||!m->barrier||!expected||!data||!channels||(channels&~63u))return SM_ARGUMENT;
 slot=expected->word[5];base=expected->word[6];if(slot>3)return SM_PROTOCOL;
 for(ch=0;ch<6;ch++)if(channels&(1u<<ch))n+=7179;
 if(n>capacity_words)return SM_ARGUMENT;
 if(header(d,slot,before))return SM_IO;
 if(before[7]!=1)return SM_PROTOCOL;
 if(!(before[0]&1)||before[1]!=expected->word[2]||before[2]!=expected->word[3]||before[3]!=expected->word[4]||before[4]!=expected->word[8]||before[5]!=expected->word[9])return SM_NO_DATA;
 if((uint64_t)m->reserved_low+before[6]!=base||(uint64_t)base+5*32768ull+7179*4ull>m->reserved_high)return SM_ARGUMENT;
 for(ch=0;ch<6;ch++)if(channels&(1u<<ch)){
  uint32_t address=base+ch*32768;
  if(m->invalidate(m->ctx,address,7179*4))return SM_IO;
  m->barrier(m->ctx);
  if(m->read(m->ctx,address,data+at,7179))return SM_IO;
  at+=7179;
 }
 m->barrier(m->ctx);
 if(header(d,slot,after))return SM_IO;
 return memcmp(before,after,sizeof before)?SM_RETRY:SM_OK;
}
