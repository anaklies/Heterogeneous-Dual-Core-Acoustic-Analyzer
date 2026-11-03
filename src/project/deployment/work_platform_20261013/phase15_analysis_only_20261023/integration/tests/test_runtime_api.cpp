#include "../control/runtime_v2.h"
#include <cassert>
#include <cstdio>
struct Mock{uint32_t m[256]={};unsigned reads=0,writes=0,fences=0;bool race=true;};
uint32_t read32(void*p,uint32_t a){auto&m=*(Mock*)p;if(a>=256&&a<384&&++m.reads==9&&m.race){m.m[6]++;for(unsigned k=64;k<96;k++)m.m[k]=k+100;}return m.m[a/4];}
void write32(void*p,uint32_t a,uint32_t d){auto&m=*(Mock*)p;m.m[a/4]=d;m.writes++;}
void fence(void*p){((Mock*)p)->fences++;}
int main(){Mock m;sm_io io{&m,read32,write32,fence};uint32_t out[32],ep=0;
 assert(sm_snapshot(&io,out,&ep,3)==1);m.m[6]=1;assert(sm_snapshot(&io,out,&ep,3)==0);assert(ep==2&&out[0]==164&&out[31]==195);
 uint32_t cfg[16];for(unsigned k=0;k<16;k++)cfg[k]=k+1;assert(sm_submit(&io,cfg)==0);assert(m.m[16]==1&&m.m[31]==16&&m.m[8]==1);assert(sm_submit(&io,cfg)==1);
 assert(m.fences>=4);puts("RUNTIME_HOST_API_PASS epoch_retry bounded_read serialized_submit");}
