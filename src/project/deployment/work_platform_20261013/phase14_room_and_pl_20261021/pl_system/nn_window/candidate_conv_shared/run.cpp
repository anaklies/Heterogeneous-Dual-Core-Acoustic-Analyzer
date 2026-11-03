#include "nn_window.h"
#include <cstdio>
static std::int16_t input[WINDOW_INPUT],phase[WINDOW_PHASE],support[WINDOW_SUPPORT],logits[WINDOW_LOGITS];
static float vector[WINDOW_VECTOR];
static std::uint64_t meta[WINDOW_META],counters[WINDOW_COUNTERS];
int main(int argc,char**argv)
{
    if(argc!=3)return 2;
    FILE*f=std::fopen(argv[1],"rb");if(!f)return 3;
    if(std::fread(input,2,WINDOW_INPUT,f)!=WINDOW_INPUT)return 4;std::fclose(f);
    nn_window(input,phase,support,logits,vector,meta,counters);
    f=std::fopen(argv[2],"wb");if(!f)return 5;
    if(std::fwrite(phase,2,WINDOW_PHASE,f)!=WINDOW_PHASE)return 6;
    if(std::fwrite(support,2,WINDOW_SUPPORT,f)!=WINDOW_SUPPORT)return 6;
    if(std::fwrite(logits,2,WINDOW_LOGITS,f)!=WINDOW_LOGITS)return 6;
    if(std::fwrite(vector,4,WINDOW_VECTOR,f)!=WINDOW_VECTOR)return 6;
    if(std::fwrite(meta,8,WINDOW_META,f)!=WINDOW_META)return 6;
    if(std::fwrite(counters,8,WINDOW_COUNTERS,f)!=WINDOW_COUNTERS)return 6;
    return std::fclose(f)?7:0;
}
