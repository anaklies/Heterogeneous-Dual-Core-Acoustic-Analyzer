/* Cold-boot profile upload only. No DSP, no hot replacement, no flash access. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"
#include "sha256.h"
#include "profile_upload.h"
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#include <process.h>
#include <sys/stat.h>
#endif
#ifndef _WIN32
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#endif
typedef struct {uint32_t *private_words;volatile uint32_t *registers;int test;uint32_t writes;} context;
static int store(void *opaque,uint32_t address,const uint32_t *data,uint32_t words){
    context *c=(context*)opaque;uint32_t i;
    if(address<0x10200000u||(address&3u)||(uint64_t)address+4ull*words>0x11000000ull)return -1;
    for(i=0;i<words;i++)((volatile uint32_t*)c->private_words)[(address-0x10200000u)/4+i]=data[i];
    c->writes+=words;return 0;
}
static void barrier(void *opaque){(void)opaque;__sync_synchronize();}
static int clean(void *opaque,uint32_t address,uint32_t bytes){(void)address;(void)bytes;barrier(opaque);return 0;}
#ifndef _WIN32
static int rd(void *opaque,uint32_t address,uint32_t *value){context*c=opaque;if(address>=4096||address%4)return -1;*value=c->registers[address/4];barrier(c);return 0;}
static int wr(void *opaque,uint32_t address,uint32_t value){context*c=opaque;if(address>=4096||address%4)return -1;c->registers[address/4]=value;barrier(c);return 0;}
static uint64_t ms(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return(uint64_t)t.tv_sec*1000+t.tv_nsec/1000000;}
#endif
static unsigned char *readfile(const char *path,size_t *size,size_t max){
    FILE*f=fopen(path,"rb");long n;unsigned char*b;if(!f)return NULL;
    if(fseek(f,0,SEEK_END)||(n=ftell(f))<1||(size_t)n>max||fseek(f,0,SEEK_SET)){fclose(f);return NULL;}
    b=malloc((size_t)n+1);if(!b){fclose(f);return NULL;}
    if(fread(b,1,(size_t)n,f)!=(size_t)n){free(b);fclose(f);return NULL;}fclose(f);b[n]=0;*size=(size_t)n;return b;
}
int main(int argc,char**argv){
    unsigned char *meta,*image;size_t meta_size,image_size;gw_json_doc doc;const gw_json_node *root,*array;
    uint32_t cfg[32];unsigned i;char hash[65],wanted[65],image_path[1024],error[128];uint8_t digest[32];context c={0};FILE*immutable;int validation=argc==3&&!strcmp(argv[1],"--validate-only");
    const char *profile=validation?argv[2]:(argc==3?argv[1]:NULL),*state=validation?NULL:(argc==3?argv[2]:NULL);
    (void)state;
    if(!profile){fprintf(stderr,"Usage: echo-bootstrap PROFILE.json STATE_DIR | --validate-only PROFILE.json\n");return 2;}
    meta=readfile(profile,&meta_size,1048576);if(!meta){fprintf(stderr,"Profile metadata cannot be read\n");return 3;}gw_json_doc_init(&doc);
    if(gw_json_parse(&doc,(const char*)meta,meta_size,32,20000,error,sizeof error)){fprintf(stderr,"Profile JSON rejected: %s\n",error);free(meta);return 3;}
    root=gw_json_root(&doc);array=gw_json_obj_get(&doc,root,"config32");
    if(gw_json_arr_count(array)!=32||gw_json_get_str(&doc,root,"image_sha256",wanted,sizeof wanted,NULL)){fprintf(stderr,"Profile schema rejected\n");return 3;}
    for(i=0;i<32;i++)if(gw_json_node_u32(gw_json_arr_at(array,i),&cfg[i])){fprintf(stderr,"Config word rejected: %u\n",i);return 3;}
    if(cfg[0]!=1||cfg[1]!=1||cfg[2]!=0x10000000u||cfg[3]!=4194304u||cfg[4]!=0x10000000u||cfg[5]!=0x11000000u||cfg[8]!=9||cfg[9]!=0x12000000u||cfg[10]!=0x01000000u||cfg[11]!=0x12000000u||cfg[12]!=0x14000000u||cfg[13]!=0x13000000u||cfg[14]){fprintf(stderr,"Unapproved cold profile layout\n");return 3;}
    if(strlen(profile)+32>=sizeof image_path)return 3;
    strcpy(image_path,profile);{char *slash=strrchr(image_path,'/'),*back=strrchr(image_path,'\\');if(back&&(!slash||back>slash))slash=back;if(slash)slash[1]=0;else image_path[0]=0;strcat(image_path,"profile_init.smi");}
    image=readfile(image_path,&image_size,64u*1024u*1024u);if(!image){fprintf(stderr,"Profile image cannot be read: %s\n",image_path);return 3;}
    {gw_sha256_ctx s;gw_sha256_init(&s);gw_sha256_update(&s,image,image_size);gw_sha256_final(&s,digest);gw_sha256_hex(digest,hash);}
    if(strcmp(hash,wanted)){fprintf(stderr,"Image hash mismatch; no memory touched\n");return 3;}
#ifdef _WIN32
    {char path[1024];const char *temp=getenv("TEMP");int fd;if(!temp)return 3;
     snprintf(path,sizeof path,"%s/echo-profile-%u.tmp",temp,(unsigned)_getpid());
     fd=_open(path,_O_CREAT|_O_EXCL|_O_RDWR|_O_BINARY|_O_TEMPORARY,_S_IREAD|_S_IWRITE);
     immutable=fd<0?NULL:_fdopen(fd,"w+b");
     if(!immutable||fwrite(image,1,image_size,immutable)!=image_size||fflush(immutable)||fseek(immutable,0,SEEK_SET)){fprintf(stderr,"Private validation stream unavailable\n");return 3;}
    }
#else
    immutable=fmemopen(image,image_size,"rb");if(!immutable){fprintf(stderr,"Immutable image stream unavailable\n");return 3;}
#endif
    free(meta);gw_json_doc_free(&doc);
    if(validation){c.test=1;c.private_words=calloc(3670016u,4);if(!c.private_words)return 3;}
    else {
#ifdef _WIN32
        fprintf(stderr,"Real boot initialization is ARM Linux only\n");return 78;
#else
        int fd;uint32_t active,pending;sm_device device;sm_identity id;char path[1024];FILE*f;
        unsigned char reserved[8];
        f=fopen("/proc/device-tree/reserved-memory/echo-analysis@10000000/reg","rb");
        if(!f||fread(reserved,1,8,f)!=8||memcmp(reserved,"\x10\x00\x00\x00\x04\x00\x00\x00",8)){fprintf(stderr,"Matched 64MiB reserved DDR missing\n");return 78;}fclose(f);
        if(access("/proc/device-tree/reserved-memory/echo-analysis@10000000/no-map",F_OK)){fprintf(stderr,"DDR no-map attribute missing\n");return 78;}
        fd=open("/dev/mem",O_RDWR|O_SYNC|O_CLOEXEC);if(fd<0)return 78;
        c.registers=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0x43c20000u);if(c.registers==MAP_FAILED)return 78;
        device=(sm_device){&c,rd,wr,barrier};
        if(sm_identify(&device,&id)||id.firmware!=0x82000001u||rd(&c,0x1c,&active)||rd(&c,0x20,&pending)||pending&1)return 78;
        if(active){
            unsigned ver,v;uint32_t cached[32];sm_snapshot snap;
            snprintf(path,sizeof path,"%s/config_active.txt",state);f=fopen(path,"rb");if(!f)return 78;
            if(fscanf(f,"%u",&ver)!=1||ver!=active){fclose(f);return 78;}
            for(i=0;i<32;i++){if(fscanf(f,"%x",&v)!=1){fclose(f);return 78;}cached[i]=v;}fclose(f);
            if(sm_read_snapshot(&device,&snap,3)||snap.word[SM_R_SESSION]!=cached[0]||cached[1]!=active)return 78;
            puts("ECHO_REUSE_CONFIRMED_NO_DDR_WRITES");return 0;
        }
        {uint32_t clips;rd(&c,0x30,&clips);if(clips)return 78;}
        c.private_words=mmap(NULL,0x00e00000u,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0x10200000u);
        if(c.private_words==MAP_FAILED)return 78;
#endif
    }
    {sm_upload_memory m={&c,store,clean,barrier,0x10000000u,4194304u};int rc=sm_upload_profile(immutable,&m);fclose(immutable);free(image);if(rc){fprintf(stderr,"Upload rejected %d; services remain disabled\n",rc);return 4;}}
    if(validation){free(c.private_words);printf("ECHO_PROFILE_VALIDATE_PASS privateWrites=%u protectedP0Writes=0\n",c.writes);return 0;}
#ifndef _WIN32
    {sm_device device={&c,rd,wr,barrier};uint64_t begin=ms();int rc;FILE*f;char path[1024];
     if(sm_commit_config(&device,cfg))return 4;
     do{struct timespec wait={0,10000000};nanosleep(&wait,NULL);rc=sm_config_status(&device,cfg[1]);}while((rc==SM_BUSY||rc==SM_NO_DATA)&&ms()-begin<5000);
     if(rc){fprintf(stderr,"PL did not confirm configuration; no success recorded\n");return 4;}
     snprintf(path,sizeof path,"%s/config_active.txt",state);f=fopen(path,"wb");if(!f)return 4;
     fprintf(f,"%u\n",cfg[1]);for(i=0;i<32;i++)fprintf(f,"%08x\n",cfg[i]);if(fclose(f))return 4;
     puts("ECHO_PROFILE_APPLIED_BY_PL");
    }
#endif
    return 0;
}
