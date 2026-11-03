#include "acoustic_frontend.h"
#include <cstdio>
#include <cmath>
#include <cstring>
#include <limits>
using namespace sixmic_frontend;
extern "C" void neural_features(const float*,std::int16_t*,unsigned*);
static std::int32_t pcm[70656];
static float previous[20412],current[20412],scratch[10206];
static std::int16_t features[153090],expected[153090];
static std::uint32_t old_meta[16],meta[16];
static const char *root="C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase14_room_and_pl_20261021/";
static int read(const char* name)
{
    char path[1024];std::snprintf(path,sizeof path,"%sexamples/%s",root,name);
    FILE*f=std::fopen(path,"rb");if(!f)return 1;
    int ok=std::fread(pcm,4,70656,f)==70656;std::fclose(f);return !ok;
}
static int save(const char* name,const void* data,size_t width,size_t count)
{
    char path[1024];std::snprintf(path,sizeof path,"%sresults/%s",root,name);
    FILE*f=std::fopen(path,"wb");if(!f)return 1;
    int ok=std::fwrite(data,width,count,f)==count;std::fclose(f);return !ok;
}
static int compare_features()
{
    unsigned clips=0;neural_features(current,expected,&clips);
    if(clips)return 1;
    return std::memcmp(features,expected,sizeof features)!=0;
}
int main()
{
    if(read("frontend_window0.bin"))return 1;
    acoustic_frontend(pcm,previous,old_meta,current,scratch,features,meta,100000,7,11,1);
    if(meta[COMMIT]!=MAGIC||meta[COMPUTED]!=162||meta[REUSED]||meta[ERROR]||compare_features())return 2;
    if(save("frontend_cold_stft.bin",current,4,20412))return 3;
    std::memcpy(previous,current,sizeof current);std::memcpy(old_meta,meta,sizeof meta);
    if(read("frontend_window1.bin"))return 4;
    acoustic_frontend(pcm,previous,old_meta,current,scratch,features,meta,104608,7,11,1);
    if(meta[COMMIT]!=MAGIC||meta[COMPUTED]!=72||meta[REUSED]!=90||meta[ERROR]||compare_features())return 5;
    for(int ch=0;ch<6;ch++)for(int f=0;f<63;f++)for(int t=0;t<15;t++) {
        int to=((ch*63+f)*27+t)*2,from=to+24;
        if(current[to]!=previous[from]||current[to+1]!=previous[from+1])return 6;
    }
    if(save("frontend_warm_stft.bin",current,4,20412) ||
       save("frontend_warm_q11.bin",features,2,153090) ||
       save("frontend_warm_meta.bin",meta,4,16))return 7;
    std::puts("FRONTEND_COLD162_WARM72_REUSED90_FEATURES_EXACT");

    // Each invalid descriptor must force a cold start. An invalid firstPCM
    // sample then fails before any FFT. These are bounded control cases.
    pcm[0]=8388608;
    int fields[]={COMMIT,VERSION,CONFIG,SESSION,START_LO,NFFT,HOP_SIZE,TIME_COUNT,BIN_COUNT,ERROR};
    for(int i=0;i<10;i++) {
        unsigned saved=old_meta[fields[i]];old_meta[fields[i]]^=1;
        acoustic_frontend(pcm,previous,old_meta,current,scratch,features,meta,104608,7,11,1);
        old_meta[fields[i]]=saved;
        if(meta[COMMIT]||meta[MODE]||meta[ERROR]!=BAD_PCM||meta[COMPUTED])return 10+i;
    }
    acoustic_frontend(pcm,previous,old_meta,current,scratch,features,meta,104608,7,11,0);
    if(meta[COMMIT]||meta[MODE]||meta[ERROR]!=BAD_PCM)return 21;
    acoustic_frontend(pcm,previous,old_meta,current,scratch,features,meta,UINT64_MAX-100,7,11,1);
    if(meta[COMMIT]||meta[ERROR]!=SAMPLE_ID_OVERFLOW)return 22;
    // t12 in the old cache becomes t0 in the new cache. The newPCM error
    // below occurs first. This case does not separately test NaN rejection.
    previous[24]=std::numeric_limits<float>::quiet_NaN();pcm[0]=0;
    // Mark all PCM invalid so this last test stops in a newFFT read. The
    // Do not report this as a standalone NaN rejection test.
    pcm[15*384*6]=8388608;
    acoustic_frontend(pcm,previous,old_meta,current,scratch,features,meta,104608,7,11,1);
    if(meta[COMMIT]||meta[ERROR]!=BAD_PCM||meta[MODE]!=1)return 23;
    std::puts("FRONTEND_DESCRIPTOR_REJECTION12_BAD_NEW_PCM_PASS");
    return 0;
}
