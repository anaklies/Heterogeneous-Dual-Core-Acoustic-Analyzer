#include "raw_cursor.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
typedef struct{uint32_t status[16],ram[1024];int mutate;} fake;
static int rd(void*p,uint32_t a,uint32_t*v){fake*f=p;if(a<0x300||a>=0x340)return -1;*v=f->status[(a-0x300)/4];return 0;}
static int wr(void*p,uint32_t a,uint32_t v){(void)p;(void)a;(void)v;return -1;}
static void barrier(void*p){(void)p;}
static int invalidate(void*p,uint32_t a,uint32_t n){(void)p;assert(a>=0x100000&&(uint64_t)a+n<=0x101000);return 0;}
static int memread(void*p,uint32_t a,uint32_t*out,uint32_t n){fake*f=p;memcpy(out,f->ram+(a-0x100000)/4,4*n);if(f->mutate){if(f->mutate==1)f->status[1]++;else{f->status[5]=253;f->status[4]=125*32;}f->mutate=0;}return 0;}
int main(void){fake f={0};f.status[0]=0x43555231;f.status[1]=1;f.status[2]=0x100000;f.status[3]=4096;f.status[4]=96;f.status[5]=131;f.status[7]=1131;f.status[11]=3;f.status[12]=7;f.status[14]=1;f.status[15]=7;
for(unsigned i=3;i<131;i++){unsigned a=(i%128)*8;f.ram[a]=0xffffffff;f.ram[a+1]=i;f.ram[a+6]=1000+i+(i>=128);}
sm_device d={&f,rd,wr,barrier};sm_memory m={&f,memread,invalidate,barrier,0x100000,0x101000};uint32_t buffer[48];sm_raw_copy result;
assert(sm_copy_raw_records(&d,&m,125,6,buffer,&result)==SM_OK);assert(result.first_sample==1125&&result.last_sample==1131&&result.sequence_gaps==1);for(unsigned i=0;i<6;i++)assert(buffer[8*i]==0xffffffff&&buffer[8*i+1]==125+i);
assert(sm_copy_raw_records(&d,&m,2,1,buffer,&result)==SM_NO_DATA);assert(sm_copy_raw_records(&d,&m,3,1,buffer,&result)==SM_NO_DATA);f.mutate=1;assert(sm_copy_raw_records(&d,&m,125,6,buffer,&result)==SM_RETRY);
f.mutate=2;assert(sm_copy_raw_records(&d,&m,125,6,buffer,&result)==SM_RETRY);
puts("RAW_COPY_PASS in-flight oldest-slot exclusion; physical ring wrap signedPCM sample gaps expired data generation change");return 0;}
