#ifndef SIXMIC_MANUAL_MEMORY_PORTS_H
#define SIXMIC_MANUAL_MEMORY_PORTS_H
#include <cstdint>
#ifdef SIXMIC_NATIVE
#include <cassert>
class NativeAXI {
    float *memory;
    unsigned read_at=0,read_left=0,write_at=0,write_left=0,responses=0;
public:
    NativeAXI(float *p):memory(p){}
    void read_request(unsigned i,unsigned n){assert(!read_left && n);read_at=i;read_left=n;}
    float read(){assert(read_left);--read_left;return memory[read_at++];}
    void write_request(unsigned i,unsigned n){assert(!write_left && n);write_at=i;write_left=n;++responses;}
    void write(float v){assert(write_left);--write_left;memory[write_at++]=v;}
    void write_response(){assert(!write_left && responses);--responses;}
};
using MemoryAXI=NativeAXI;
#else
#include "hls_burst_maxi.h"
using MemoryAXI=hls::burst_maxi<float>;
#endif

// One16-word line per reader. No outstanding request survives get().
// Small local lines are not large frame buffers in BRAM.
class ReadPort {
    MemoryAXI port;
    float line[16];
    unsigned base=0,limit=0,offset=0,arena_words=0;
    bool valid=false;
public:
    ReadPort(MemoryAXI p,unsigned at,unsigned words):port(p),offset(at),arena_words(words){}
    bool length(unsigned n){limit=n;valid=false;return offset<=arena_words && n<=arena_words-offset;}
    float get(unsigned i){
#pragma HLS INLINE
        unsigned start=i&~15u;
        if(!valid || base!=start){
            unsigned count=limit-start;if(count>16)count=16;
            port.read_request(offset+start,count);
            for(unsigned k=0;k<count;k++){
#pragma HLS PIPELINE II=1
                line[k]=port.read();
            }
            base=start;valid=true;
        }
        return line[i&15];
    }
};

class WritePort {
    MemoryAXI port;
    float line[16];
    unsigned base=0,offset=0,arena_words=0;
    std::uint16_t dirty=0;
    bool valid=false;
public:
    WritePort(MemoryAXI p,unsigned at,unsigned words):port(p),offset(at),arena_words(words){}
    bool length(unsigned n){return offset<=arena_words && n<=arena_words-offset;}
    void flush(){
#pragma HLS INLINE
        unsigned i=0;
        while(i<16){
#pragma HLS LOOP_TRIPCOUNT min=1 max=16
            if(!(dirty&(1u<<i))){++i;continue;}
            unsigned first=i;
            while(i<16 && (dirty&(1u<<i)))++i;
            port.write_request(offset+base+first,i-first);
            for(unsigned k=first;k<i;k++){
#pragma HLS PIPELINE II=1
                port.write(line[k]);
            }
            port.write_response();
        }
        dirty=0;
    }
    void put(unsigned i,float value){
#pragma HLS INLINE
        unsigned start=i&~15u;
        if(valid && base!=start)flush();
        if(!valid || base!=start){base=start;valid=true;}
        line[i&15]=value;dirty|=std::uint16_t(1u<<(i&15));
    }
    float get(unsigned i){
#pragma HLS INLINE
        if(valid && base==(i&~15u) && (dirty&(1u<<(i&15))))return line[i&15];
        flush();
        port.read_request(offset+i,1);
        return port.read();
    }
};
#endif
