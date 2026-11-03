#include <stdint.h>
extern void nearfield_music(const int64_t*,const int64_t*,const int64_t*,const int64_t*,const float*,const float*,int32_t*);
extern "C" __declspec(dllexport) void candidate_music(const int64_t*a,const int64_t*b,const int64_t*c,const int64_t*d,const float*e,const float*f,int32_t*g){nearfield_music(a,b,c,d,e,f,g);}
