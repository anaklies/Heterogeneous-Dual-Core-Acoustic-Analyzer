#include <cmath>
#include <cstdint>
#include "../../../phase14_room_and_pl_20261021/pl_system/analysis_dma/memory_ports.h"
static unsigned bits(float f){union{float f;unsigned u;}x;x.f=f;return x.u;}
static float real(unsigned u){union{float f;unsigned u;}x;x.u=u;return x.f;}
static bool overlap(unsigned a,unsigned n,unsigned b,unsigned m)
{return n&&m&&uint64_t(a)<uint64_t(b)+m&&uint64_t(b)<uint64_t(a)+n;}
static bool region(unsigned a,unsigned n,unsigned size){return a<=size&&n<=size-a;}

// A bounded PL scalar instruction engine, not a PS software DSP task.
// A command executes at most512 instructions, then checkpoints its context.
extern "C" void scalar_engine(MemoryAXI memory,unsigned descriptor,unsigned arena_words,unsigned source_slot,unsigned expected_session,unsigned expected_config,unsigned source_frame,unsigned sample_low,unsigned sample_high,unsigned *status)
{
#pragma HLS INTERFACE m_axi port=memory offset=slave bundle=memory depth=4194304 num_read_outstanding=1 num_write_outstanding=1 max_read_burst_length=16 max_write_burst_length=16
#pragma HLS INTERFACE s_axilite port=memory bundle=control
#pragma HLS INTERFACE s_axilite port=descriptor bundle=control
#pragma HLS INTERFACE s_axilite port=arena_words bundle=control
#pragma HLS INTERFACE s_axilite port=source_slot bundle=control
#pragma HLS INTERFACE s_axilite port=expected_session bundle=control
#pragma HLS INTERFACE s_axilite port=expected_config bundle=control
#pragma HLS INTERFACE s_axilite port=source_frame bundle=control
#pragma HLS INTERFACE s_axilite port=sample_low bundle=control
#pragma HLS INTERFACE s_axilite port=sample_high bundle=control
#pragma HLS INTERFACE s_axilite port=status bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION operation instances=fadd limit=1
#pragma HLS ALLOCATION operation instances=fsub limit=1
#pragma HLS ALLOCATION operation instances=fmul limit=1
#pragma HLS ALLOCATION operation instances=fdiv limit=1
    *status=0;
    if(!arena_words||arena_words>4194304||source_slot>3||descriptor<524288||!region(descriptor,16,arena_words)){*status=1;return;}
    ReadPort read(memory,0,arena_words);WritePort write(memory,0,arena_words);
    read.length(arena_words);write.length(arena_words);
    unsigned d[16];for(unsigned i=0;i<16;i++)d[i]=bits(read.get(descriptor+i));
    unsigned code=d[2],length=d[3],context=d[4],begin=d[5],count=d[6],out=d[7],out_count=d[8],budget=d[9];
    if(d[0]!=0x414c5531||d[1]!=1||!length||length>1024||!budget||budget>512||d[10]>2||d[15]||
       code<524288||context<524288||out<524304||
       !region(code,4*length,arena_words)||!region(context,80,arena_words)||
       !region(begin,count,arena_words)||!region(out,out_count,arena_words)||
       overlap(descriptor,16,context,80)||overlap(code,4*length,context,80)||overlap(descriptor,16,code,4*length)||
       overlap(out-16,out_count+16,descriptor,16)||overlap(out-16,out_count+16,code,4*length)||overlap(out-16,out_count+16,context,80))
    {*status=2;return;}
    if(d[11]!=expected_session||d[12]!=expected_config){*status=3;return;}
    unsigned pcm_begin=source_slot*16384,fft_begin=262144+source_slot*65536;
    bool pinned_input=(begin>=pcm_begin&&uint64_t(begin)+count<=uint64_t(pcm_begin)+12288)||
                      (begin>=fft_begin&&uint64_t(begin)+count<=uint64_t(fft_begin)+49152);
    if(begin<524288&&!pinned_input){*status=2;return;}
    float f[32];unsigned u[32],pc=0,total=0;bool done=false;
#pragma HLS BIND_STORAGE variable=f type=ram_2p impl=bram
#pragma HLS BIND_STORAGE variable=u type=ram_2p impl=bram
    // Commit sequence spans automatic restarts within one generation. A reader
    // can reject ABA even if the same slot and instruction count recur.
    if(bits(read.get(context))==0x43545831&&bits(read.get(context+15))==d[14]&&
       bits(read.get(context+2))==d[11]&&bits(read.get(context+3))==d[12])
        total=bits(read.get(context+11));
    bool restart=d[10]==1;
    if(d[10]==2) {
        bool same=bits(read.get(context))==0x43545831&&bits(read.get(context+15))==d[14]&&bits(read.get(context+14))==source_slot;
        unsigned bind[9]={d[11],d[12],d[13],code,length,begin,count,out,out_count};
        for(unsigned i=0;i<9;i++)same=same&&bits(read.get(context+2+i))==bind[i];
        restart=!same||(bits(read.get(context+12))&&bits(read.get(context+13))==0);
    }
    if(restart)for(unsigned i=0;i<32;i++){f[i]=0;u[i]=0;}
    else {
        if(bits(read.get(context))!=0x43545831){*status=3;return;}
        unsigned bind[10]={d[11],d[12],d[13],code,length,begin,count,out,out_count,d[14]};
        for(unsigned i=0;i<9;i++)if(bits(read.get(context+2+i))!=bind[i]){*status=3;return;}
        if(bits(read.get(context+15))!=d[14]||bits(read.get(context+14))!=source_slot){*status=3;return;}
        pc=bits(read.get(context+1));total=bits(read.get(context+11));
        if(bits(read.get(context+13))||bits(read.get(context+12))){*status=3;return;}
        for(unsigned i=0;i<32;i++){f[i]=read.get(context+16+i);if(!std::isfinite(f[i])){*status=3;return;}}
        for(unsigned i=0;i<32;i++)u[i]=bits(read.get(context+48+i));
    }
    // Invalidate BEFORE any program STORE. Both publication and context are
    // fenced on the same AXI master; no old DONE survives an in-progress job.
    write.put(out-16,real(0));write.put(context,real(0));write.flush();
    unsigned error=0,request=0;
    for(unsigned step=0;step<budget;step++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=512
        if(pc>=length){error=4;break;}
        unsigned ins=bits(read.get(code+4*pc)),imm=bits(read.get(code+4*pc+1)),target=bits(read.get(code+4*pc+2));
        if(bits(read.get(code+4*pc+3))||ins>>23){error=4;break;}
        unsigned op=ins&255,rd=(ins>>8)&31,ra=(ins>>13)&31,rb=(ins>>18)&31;
        float a=f[ra],b=f[rb],v=0;bool set_float=false;
        if(total==0xffffffffu){error=7;break;}++pc;++total;
        if(op==0){done=true;break;}
        else if(op==1){v=real(imm);set_float=true;}
        else if(op==2||op==3) {
            if(target>2||(op==3&&target==2)){error=4;break;}
            uint64_t address=uint64_t(imm)+u[ra]+(target==2?out:(target?(op==2?begin:out):0));
            if(op==2) {
                if(target==2){if(address<out||address>=uint64_t(out)+out_count){error=5;break;}}
                else if(address<begin||address>=uint64_t(begin)+count){error=5;break;}
                v=read.get((unsigned)address);set_float=true;
            } else {
                if(address<out||address>=uint64_t(out)+out_count||!std::isfinite(f[rd])){error=5;break;}
                write.put((unsigned)address,f[rd]);
                // Program LOAD may read a prior STORE. Do not retain a stale
                // reader line across stores; only one shared AXI channel exists.
                write.flush();read.length(arena_words);
            }
        } else if(op>=4&&op<=13) {
            if(!std::isfinite(a)||!std::isfinite(b)){error=6;break;}
            if(op==4)v=a+b;else if(op==5)v=a-b;else if(op==6)v=a*b;
            else if(op==7){if(b==0){error=6;break;}v=a/b;}
            else if(op==8){if(a<0){error=6;break;}v=std::sqrt(a);}
            else if(op==9){if(a<=0){error=6;break;}v=std::log(a);}
            else if(op==10)v=std::exp(a);
            else if(op==11)v=std::fmin(a,b);else if(op==12)v=std::fmax(a,b);else v=std::fabs(a);
            set_float=true;
        } else if(op==14)u[rd]=imm;
        else if(op==15){if(uint64_t(u[ra])+imm>0xffffffffu){error=6;break;}u[rd]=u[ra]+imm;}
        else if(op==16){if(u[ra]<imm){if(target>=length){error=4;break;}pc=target;}}
        else if(op==17){if(imm>=length){error=4;break;}pc=imm;}
        else if(op==18){v=float(u[ra]);set_float=true;}
        else if(op==19){if(a<b){if(target>=length){error=4;break;}pc=target;}}
        else if(op==20||op==21) {
            if(target>2||(op==21&&target==2)){error=4;break;}
            uint64_t address=uint64_t(imm)+u[ra]+(target==2?out:(target?(op==20?begin:out):0));
            if(op==20){
                if(target==2){if(address<out||address>=uint64_t(out)+out_count){error=5;break;}}
                else if(address<begin||address>=uint64_t(begin)+count){error=5;break;}
                u[rd]=bits(read.get((unsigned)address));}
            else {if(address<out||address>=uint64_t(out)+out_count){error=5;break;}write.put((unsigned)address,real(u[rd]));write.flush();read.length(arena_words);}
        } else if(op==22){v=float((int32_t)u[ra]);set_float=true;}
        else if(op==23) {
            if(imm>3||(out&4095)||out_count<16384||pc>=length){error=4;break;}
            request=0x40000000u|(imm<<28)|((out>>12)<<18);break;
        }
        else if(op==24){if(u[ra]<u[rb]){error=6;break;}u[rd]=u[ra]-u[rb];}
        else if(op==26){if(imm>2){error=4;break;}u[rd]=imm==0?source_frame:(imm==1?sample_low:sample_high);}
        else {error=4;break;}
        if(set_float){if(!std::isfinite(v)){error=6;break;}f[rd]=v;}
    }
    // Status/valid consumers must wait for the actual AXI completion fence.
    write.flush();
    write.put(context,real(0));write.flush();
    write.put(context+1,real(pc));
    unsigned bind[9]={d[11],d[12],d[13],code,length,begin,count,out,out_count};
    for(unsigned i=0;i<9;i++)write.put(context+2+i,real(bind[i]));
    write.put(context+11,real(total));write.put(context+12,real(done));write.put(context+13,real(error));
    write.put(context+14,real(source_slot));write.put(context+15,real(d[14]));
    for(unsigned i=0;i<32;i++)write.put(context+16+i,f[i]);
    for(unsigned i=0;i<32;i++)write.put(context+48+i,real(u[i]));
    write.flush();write.put(context,real(0x43545831));write.flush();
    unsigned meta[15]={total,d[11],d[12],d[14],d[13],source_frame,sample_low,sample_high,
                       source_slot,out_count,descriptor,error,pc,done?1u:0u,0};
    for(unsigned i=0;i<15;i++)write.put(out-15+i,real(meta[i]));
    write.flush();
    if(done&&!error){write.put(out-16,real(0x52534c54));write.flush();}
    *status=error|(pc<<8)|(done?0x80000000u:0)|request;
}

#ifdef SIXMIC_NATIVE
extern "C" void scalar_native(float *memory,unsigned descriptor,unsigned arena_words,unsigned source_slot,unsigned *status)
{if(descriptor>arena_words||arena_words-descriptor<16){*status=1;return;}scalar_engine(MemoryAXI(memory),descriptor,arena_words,source_slot,bits(memory[descriptor+11]),bits(memory[descriptor+12]),0,0,0,status);}
extern "C" void scalar_native_checked(float *memory,unsigned descriptor,unsigned arena_words,unsigned source_slot,unsigned session,unsigned config,unsigned *status)
{scalar_engine(MemoryAXI(memory),descriptor,arena_words,source_slot,session,config,0,0,0,status);}
extern "C" void scalar_native_meta(float *memory,unsigned descriptor,unsigned arena_words,unsigned slot,unsigned session,unsigned config,unsigned frame,unsigned low,unsigned high,unsigned *status)
{scalar_engine(MemoryAXI(memory),descriptor,arena_words,slot,session,config,frame,low,high,status);}
#endif
