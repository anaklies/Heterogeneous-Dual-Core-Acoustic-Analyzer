#include "fft_snapshot.h"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
typedef struct{uint32_t h[8];unsigned reads;int mutate;}fake;
static int rd(void*p,uint32_t a,uint32_t*v){fake*f=p;if(a<0x400||a>=0x420)return -1;*v=f->h[(a-0x400)/4];return 0;}
static void barrier(void*p){(void)p;}
static int inv(void*p,uint32_t a,uint32_t n){(void)p;assert(a>=0x10100000u&&(uint64_t)a+n<=0x10140000u);return 0;}
static int memread(void*p,uint32_t a,uint32_t*out,uint32_t n){fake*f=p;f->reads++;for(uint32_t i=0;i<n;i++)out[i]=a+4*i;if(f->mutate==1)f->h[0]=0;else if(f->mutate==2)f->h[1]++;return 0;}
int main(void){fake f={{1,9,7,3,1000,0,0x100000,1},0,0};sm_device d={&f,rd,NULL,barrier};sm_memory m={&f,memread,inv,barrier,0x10000000,0x11000000};sm_snapshot s={0};s.word[2]=9;s.word[3]=7;s.word[4]=3;s.word[5]=0;s.word[6]=0x10100000;s.word[8]=1000;uint32_t*out=malloc(2*7179*4);assert(out);
assert(sm_copy_fft_snapshot(&d,&m,&s,0x21,out,2*7179)==SM_OK);assert(out[0]==0x10100000u&&out[7179]==0x10128000u);
f.mutate=1;assert(sm_copy_fft_snapshot(&d,&m,&s,0x21,out,2*7179)==SM_RETRY);unsigned old=f.reads;assert(sm_copy_fft_snapshot(&d,&m,&s,0x21,out,2*7179)==SM_NO_DATA&&f.reads==old);
f.h[0]=1;f.mutate=2;assert(sm_copy_fft_snapshot(&d,&m,&s,1,out,2*7179)==SM_RETRY);
free(out);puts("FFT_SNAPSHOT_PASS ready/frame/session/source checks reject overwrite without mailbox epoch change");return 0;}
