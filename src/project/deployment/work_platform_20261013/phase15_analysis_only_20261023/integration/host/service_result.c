#include "service_result.h"
#include <string.h>
int sm_copy_service(const sm_memory *m,uint32_t output,uint32_t n,uint32_t session,uint32_t config,uint32_t *data,sm_service_result *meta,unsigned attempts){
 sm_service_result a,b;unsigned k;
 if(!m||!m->read||!m->invalidate||!m->barrier||!meta||(!data&&n)||!attempts||output<64||output%4||m->reserved_high<=m->reserved_low||output-64<m->reserved_low||(uint64_t)output+4ull*n>m->reserved_high)return SM_ARGUMENT;
 for(k=0;k<attempts;k++){
  if(m->invalidate(m->ctx,output-64,64))return SM_IO;
  m->barrier(m->ctx);
  if(m->read(m->ctx,output-64,a.word,16))return SM_IO;
  if(a.word[0]!=0x52534c54u)return SM_BUSY;
  if(a.word[2]!=session||a.word[3]!=config)return SM_REJECTED;
  if(a.word[12]!=0||a.word[14]!=1||n>a.word[10])return SM_NO_DATA;
  if(n){if(m->invalidate(m->ctx,output,4*n))return SM_IO;
  m->barrier(m->ctx);if(m->read(m->ctx,output,data,n))return SM_IO;}
  m->barrier(m->ctx);if(m->invalidate(m->ctx,output-64,64))return SM_IO;
  m->barrier(m->ctx);
  if(m->read(m->ctx,output-64,b.word,16))return SM_IO;
  if(!memcmp(a.word,b.word,sizeof a.word)){*meta=a;return SM_OK;}
 }
 return SM_RETRY;
}
