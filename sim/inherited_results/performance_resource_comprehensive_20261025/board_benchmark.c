// Management and measurement only; all workload arithmetic runs in the RC1 PL.
#include <stdint.h>
#include "workload_fixtures.h"
#define HOST ((volatile uint32_t *)0x43C20000u)
#define ARENA ((volatile uint32_t *)0x10000000u)
#define RESULT ((volatile uint32_t *)0x02010000u)
#define OUTPUT_LOG ((volatile uint32_t *)0x02200000u)
#define TRACE ((volatile uint32_t *)0x03000000u)
#define GT ((volatile uint32_t *)0xF8F00200u)
#define HZ 333333333u
#define STRIDE 64u
static void fence(void){__asm__ volatile("dsb sy" ::: "memory");}
static uint64_t ticks(void){uint32_t a,b,c;do{a=GT[1];b=GT[0];c=GT[1];}while(a!=c);return((uint64_t)a<<32)|b;}
static void error(uint32_t e){RESULT[2]=e;RESULT[1]=0xFFFFFFFF;fence();}
static void observe(uint32_t phase){
    uint32_t epoch=HOST[0x18/4],n=RESULT[7];
    if(!epoch || epoch==RESULT[8] || n>=4096)return;
    uint64_t t=ticks();uint32_t frame=HOST[0x100/4+2],config=HOST[0x100/4+3];
    uint32_t cycles=HOST[0x100/4+7],missed=HOST[0x100/4+12],drop=HOST[0x100/4+13],failed=HOST[0x100/4+16],fault=HOST[0x100/4+10];
    if(epoch!=HOST[0x18/4])return;
    volatile uint32_t *row=TRACE+n*12;
    row[0]=phase;row[1]=epoch;row[2]=frame;row[3]=config;row[4]=(uint32_t)t;row[5]=t>>32;row[6]=cycles;row[7]=missed;row[8]=drop;row[9]=failed;row[10]=fault;row[11]=0;
    RESULT[7]=n+1;RESULT[8]=epoch;
}
static int configure(const uint32_t *c,uint32_t version,uint32_t flags,uint32_t phase){
    RESULT[6]=phase;
    if(HOST[0x20/4]&1)return 0;
    for(unsigned i=0;i<32;i++)HOST[0x40/4+i]=i==1?version:i==8?flags:c[i];
    fence();HOST[0x20/4]=1;fence();uint64_t t=ticks();
    while(HOST[0x1C/4]!=version){observe(phase);if(ticks()-t>(uint64_t)HZ*4)return 0;}return 1;
}
static int install(const Workload *w,uint32_t version,uint32_t generation,uint32_t budget){
    if(w->words<6 || w->image[0]!=0x31494D53 || w->image[1]!=4194304 || w->image[2]!=524288 || w->image[3]!=3670016)return 0;
    for(unsigned i=524288;i<4194304;i++)ARENA[i]=0;
    unsigned pos=4;
    while(pos+2<=w->words){uint32_t at=w->image[pos++],n=w->image[pos++];if(!at&&!n)break;
        if(at<524288 || at>4194304 || n>4194304-at || n>w->words-pos)return 0;
        for(unsigned i=0;i<n;i++)ARENA[at+i]=w->image[pos++];}
    for(unsigned slot=0;slot<4;slot++){
        for(unsigned family=0;family<2;family++){
            unsigned d=(family?1048576:P2_TABLE)+16*slot;
            ARENA[d+9]=budget;ARENA[d+11]=1;ARENA[d+12]=version;ARENA[d+14]=generation;}}
    fence();return 1;
}
static int job(const Workload *w,unsigned index,unsigned trial,uint32_t *version){
    unsigned number=index*4+trial;volatile uint32_t *log=RESULT+32+number*STRIDE;
    const unsigned sequence[4]={64,512,512,64};unsigned budget=sequence[trial];
    log[0]=index;log[1]=trial;log[2]=budget;log[3]=w->count;
    RESULT[1]=10+number;fence();
    if(!configure(w->config,++*version,0,number)){error(100+number);return 0;}
    if(!install(w,*version+1,number+1,budget)){error(200+number);return 0;}
    volatile uint32_t *head=ARENA+w->output-16;
    head[0]=0x54535431;fence();uint64_t activation=ticks();
    if(!configure(w->config,++*version,2,number)){error(300+number);return 0;}
    while(head[0]==0x54535431){observe(number);if(ticks()-activation>(uint64_t)HZ*25){error(400+number);return 0;}}
    uint64_t start=ticks();if(head[0]!=0){error(500+number);return 0;}
    while(head[0]!=0x52534C54){observe(number);if(ticks()-activation>(uint64_t)HZ*25){error(600+number);return 0;}}
    uint64_t finish=ticks();fence();uint64_t elapsed=finish-start,total=finish-activation;
    log[4]=(uint32_t)total;log[5]=total>>32;log[6]=(uint32_t)elapsed;log[7]=elapsed>>32;
    for(unsigned i=0;i<16;i++)log[8+i]=head[i];
    if(head[2]!=1 || head[3]!=*version || head[12] || head[14]!=1){error(700+number);return 0;}
    volatile uint32_t *target=OUTPUT_LOG+number*4096;
    for(unsigned i=0;i<w->count;i++)target[i]=ARENA[w->output+i];
    if(trial)for(unsigned i=0;i<w->count;i++)if(target[i]!=OUTPUT_LOG[index*4*4096+i]){log[24]=i+1;error(800+number);return 0;}
    log[25]=1;RESULT[4]=number+1;fence();return 1;
}
static int steady(const Workload *w,unsigned phase,uint32_t flags,uint32_t budget,uint32_t *version){
    if(!configure(w->config,++*version,0,phase)){error(900+phase);return 0;}
    if(!install(w,*version+1,100+phase,budget)){error(910+phase);return 0;}
    if(!configure(w->config,++*version,flags,phase)){error(920+phase);return 0;}
    unsigned n=0,warm=0,done_seen=0;uint32_t first=0,last=0,bg0=0,last_source=0;
    uint64_t start=0,end=0,limit=ticks();uint32_t peak=0;
    volatile uint32_t *head=ARENA+w->output-16;
    while(n<51){
        uint32_t epoch=HOST[0x18/4],snapshot_version=HOST[0x100/4+3],p0cycles=HOST[0x100/4+7];
        uint32_t confirm=HOST[0x18/4];
        if(epoch==confirm && epoch!=last && snapshot_version==*version){
            uint64_t now=ticks();observe(phase);
            last=epoch;
            if(warm<3){warm++;continue;}
            if(p0cycles>peak)peak=p0cycles;
            if(!n){start=now;first=epoch;bg0=HOST[0x100/4+14];}
            end=now;n++;
        }
        if(head[0]==0x52534C54 && head[3]==*version && head[6]!=last_source){last_source=head[6];done_seen++;}
        if(ticks()-limit>(uint64_t)HZ*12){error(930+phase);return 0;}
    }
    volatile uint32_t *r=RESULT+2300+(phase-100)*16;
    uint64_t dt=end-start;r[0]=phase;r[1]=first;r[2]=last;r[3]=dt;r[4]=dt>>32;r[5]=peak;r[6]=HOST[0x14/4];r[7]=*version;
    r[8]=bg0;r[9]=HOST[0x100/4+14];r[10]=done_seen;r[11]=flags;
    // Event fault[3] is bit14 (the event fault field is eight bits wide).
    // Keep and report it; with event monitoring disabled it is not a core
    // transport failure. Only these two known warnings are expected here.
    if(flags && (r[9]<=bg0 || !done_seen || (r[6]&~0x00804000u))){error(940+phase);return 0;}
    return 1;
}
void benchmark_main(void){
    for(unsigned i=0;i<4096;i++)RESULT[i]=0;
    RESULT[0]=0x43424D31;RESULT[1]=1;RESULT[3]=HZ;GT[2]|=1;fence();
    if(HOST[0]!=0x534D4132 || HOST[1]!=3 || HOST[2]!=0x82000001){error(1);return;}
    uint32_t version=HOST[0x1C/4];
    #ifndef STEADY_ONLY
    for(unsigned i=0;i<WORKLOADS;i++)for(unsigned k=0;k<4;k++)if(!job(&tasks[i],i,k,&version))return;
    #endif
    if(!steady(&tasks[2],100,0,64,&version))return;
    if(!steady(&tasks[2],101,1,512,&version))return;
    if(!steady(&tasks[5],102,1,512,&version))return;
    if(!configure(tasks[0].config,++version,0,103)){error(999);return;}
    RESULT[5]=version;RESULT[1]=100;fence();
}
