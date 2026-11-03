#include "raw_cursor.h"
#include <string.h>

int sm_read_raw_cursor(const sm_device *d,sm_raw_cursor *out,unsigned attempts){
    sm_raw_cursor a,b;
    unsigned i,k;
    if(!d||!d->read||!d->barrier||!out||!attempts)return SM_ARGUMENT;
    for(k=0;k<attempts;k++){
        for(i=0;i<16;i++)if(d->read(d->ctx,0x300+4*i,&a.word[i]))return SM_IO;
        d->barrier(d->ctx);
        for(i=0;i<16;i++)if(d->read(d->ctx,0x300+4*i,&b.word[i]))return SM_IO;
        if(memcmp(&a,&b,sizeof a))continue;
        if(a.word[0]!=0x43555231u||a.word[14]!=1)return SM_PROTOCOL;
        if(!(a.word[15]&1u))return SM_NO_DATA;
        if((a.word[15]&32u)||a.word[3]<4096||(a.word[3]&(a.word[3]-1))||a.word[4]>=a.word[3]||a.word[4]%32)return SM_PROTOCOL;
        *out=a;return SM_OK;
    }
    return SM_RETRY;
}
static int read_part(const sm_memory*m,uint32_t address,uint32_t *dst,uint32_t frames){
    if(m->invalidate(m->ctx,address,32*frames))return SM_IO;
    m->barrier(m->ctx);
    return m->read(m->ctx,address,dst,8*frames)?SM_IO:SM_OK;
}
int sm_copy_raw_records(const sm_device*d,const sm_memory*m,uint64_t index,uint32_t frames,uint32_t *records,sm_raw_copy*out){
    sm_raw_cursor before,after;
    uint64_t total,new_total,available,first,last,previous;
    uint32_t capacity,start,n1,i;
    int status;
    if(!m||!m->read||!m->invalidate||!m->barrier||!records||!out||!frames||frames>32768)return SM_ARGUMENT;
    status=sm_read_raw_cursor(d,&before,4);if(status)return status;
    capacity=before.word[3]/32;
    if(before.word[2]<m->reserved_low||(uint64_t)before.word[2]+before.word[3]>m->reserved_high)return SM_ARGUMENT;
    total=sm_join_u64(before.word[5],before.word[6]);available=total<capacity?total:capacity-1;
    if(((total&(capacity-1))<<5)!=before.word[4])return SM_RETRY;
    if(index>total||frames>total-index||index<total-available)return SM_NO_DATA;
    start=(uint32_t)(index&(capacity-1));n1=capacity-start;if(n1>frames)n1=frames;
    status=read_part(m,before.word[2]+start*32,records,n1);if(status)return status;
    if(frames>n1){status=read_part(m,before.word[2],records+8*n1,frames-n1);if(status)return status;}
    m->barrier(m->ctx);
    status=sm_read_raw_cursor(d,&after,4);if(status)return status;
    new_total=sm_join_u64(after.word[5],after.word[6]);
    if(before.word[1]!=after.word[1]||before.word[2]!=after.word[2]||before.word[3]!=after.word[3]||before.word[11]!=after.word[11]||before.word[12]!=after.word[12]||new_total<total||new_total-index>=capacity)return SM_RETRY;
    first=sm_join_u64(records[6],records[7]);previous=first;out->sequence_gaps=0;
    for(i=1;i<frames;i++){
        last=sm_join_u64(records[8*i+6],records[8*i+7]);
        if(last<=previous)return SM_RETRY;
        if(last-previous>1)out->sequence_gaps++;
        previous=last;
    }
    out->cursor=before;out->first_sample=first;out->last_sample=previous;return SM_OK;
}
