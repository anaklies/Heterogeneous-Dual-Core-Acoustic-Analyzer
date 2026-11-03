#include "service_result.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef struct{uint32_t words[128];int mutate;} fake;
static int readmem(void *p,uint32_t a,uint32_t *out,uint32_t n){fake*f=p;memcpy(out,f->words+a/4,n*4);if(a==256&&f->mutate){f->words[48]=0;f->mutate=0;}return 0;}
static int invalidate(void*p,uint32_t a,uint32_t n){(void)p;(void)a;(void)n;return 0;}
static void fence(void*p){(void)p;}
int main(void){fake f={0};sm_memory m={&f,readmem,invalidate,fence,0,512};sm_service_result h;uint32_t out[4];f.words[48]=0x52534c54;f.words[49]=22;f.words[50]=3;f.words[51]=7;f.words[58]=4;f.words[62]=1;f.words[64]=123;
assert(sm_copy_service(&m,256,4,3,7,out,&h,2)==SM_OK&&out[0]==123);
f.mutate=1;assert(sm_copy_service(&m,256,4,3,7,out,&h,1)==SM_RETRY);assert(sm_copy_service(&m,256,4,3,7,out,&h,1)==SM_BUSY);
f.words[48]=0x52534c54;assert(sm_copy_service(&m,256,4,3,8,out,&h,1)==SM_REJECTED);assert(sm_copy_service(&m,256,5,3,7,out,&h,1)==SM_NO_DATA);assert(sm_copy_service(&m,16,4,3,7,out,&h,1)==SM_ARGUMENT);puts("SERVICE_COPY_PASS coherent snapshot partial invalidation session/config and bounds");return 0;}
