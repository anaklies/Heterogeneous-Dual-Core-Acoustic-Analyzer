#include <stdint.h>
extern void track_sources(const int32_t*,float,bool,int32_t*);
extern void track_sources_candidate(const int32_t*,float,bool,int32_t*);
extern "C" __declspec(dllexport) void before(const int32_t*i,float d,bool r,int32_t*o){track_sources(i,d,r,o);}
extern "C" __declspec(dllexport) void candidate(const int32_t*i,float d,bool r,int32_t*o){track_sources_candidate(i,d,r,o);}
