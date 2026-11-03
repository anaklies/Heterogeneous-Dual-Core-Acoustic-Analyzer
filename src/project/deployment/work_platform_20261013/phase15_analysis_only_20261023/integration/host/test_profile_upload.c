#include "profile_upload.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
typedef struct{uint32_t *p,writes;} fake;
static FILE *mutating_file;static int mutated;
static int wr(void*ctx,uint32_t a,const uint32_t*p,uint32_t n){fake*f=ctx;if(mutating_file&&!mutated){unsigned char zero[4]={0};mutated=1;assert(!fseek(mutating_file,16,SEEK_SET));assert(fwrite(zero,1,4,mutating_file)==4);fflush(mutating_file);}assert(a>=0x10200000u&&(uint64_t)a+n*4ull<=0x11000000u);memcpy(f->p+(a-0x10000000u)/4,p,4*n);f->writes++;return 0;}
static int clean(void*c,uint32_t a,uint32_t n){(void)c;(void)a;(void)n;return 0;}
static void barrier(void*c){(void)c;}
int main(int argc,char**argv){assert(argc==2);fake f={calloc(4194304,4),0};assert(f.p);memset(f.p,0xa5,4194304*4);sm_upload_memory m={&f,wr,clean,barrier,0x10000000u,4194304};FILE*file=fopen(argv[1],"rb");assert(file);assert(sm_upload_profile(file,&m)==SM_OK);fclose(file);assert(f.p[0]==0xa5a5a5a5&&f.p[524287]==0xa5a5a5a5&&f.p[524288]==0x414c5531&&f.p[4194303]==0);
file=fopen(argv[1],"rb");assert(file);FILE *copy=fopen("tmp/profile_upload_mutating.smi","w+b");assert(copy);unsigned char buffer[1024];size_t length;while((length=fread(buffer,1,sizeof buffer,file)))assert(fwrite(buffer,1,length,copy)==length);fclose(file);fflush(copy);mutating_file=copy;memset(f.p,0xa5,4194304*4);assert(sm_upload_profile(copy,&m)==SM_OK&&mutated);assert(f.p[0]==0xa5a5a5a5&&f.p[524288]==0x414c5531);mutating_file=NULL;fclose(copy);
unsigned saved=f.writes;file=fopen("tmp/profile_upload_invalid.bin","w+b");assert(file);fwrite("SMI1",1,4,file);assert(sm_upload_profile(file,&m)==SM_PROTOCOL&&f.writes==saved);fclose(file);free(f.p);puts("PROFILE_UPLOAD_PASS immutable snapshot resists mid-upload file mutation private-only writes");return 0;}
