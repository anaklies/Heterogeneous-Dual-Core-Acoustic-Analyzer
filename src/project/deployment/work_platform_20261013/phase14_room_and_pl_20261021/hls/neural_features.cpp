#include <cmath>
#include <cstdint>
static float stable_hypot(float x,float y)
{
    float ax=std::fabs(x),ay=std::fabs(y),m=ax>ay?ax:ay;
    if(m==0)return 0;
    x/=m;y/=m;return m*std::sqrt(x*x+y*y);
}
static std::int16_t quantize(float x,unsigned &saturations)
{
    float scaled=x*2048.f;
    if(scaled>32767){saturations++;return 32767;}
    if(scaled< -32768){saturations++;return -32768;}
    int q=(int)scaled;
    float fraction=std::fabs(scaled-q);
    if(fraction>.5f||(fraction==.5f&&(q&1)))q+=scaled>=0?1:-1;
    return (std::int16_t)q;
}
// X is channel x63frequency x27time, interleavedcomplex unscaledPCM-countFFT.
// This core does notreplace FFT1536 or inject fabricatedobservations.
extern "C" void neural_features(const float X[20412],std::int16_t out[153090],unsigned *saturations)
{
#pragma HLS INTERFACE m_axi port=X offset=slave bundle=audio depth=20412
#pragma HLS INTERFACE m_axi port=out offset=slave bundle=results depth=153090
#pragma HLS INTERFACE s_axilite port=X bundle=control
#pragma HLS INTERFACE s_axilite port=out bundle=control
#pragma HLS INTERFACE s_axilite port=saturations bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    static const float mic[6][3]={{0,.1299038106f,-.076f},{-.1125f,-.0649519053f,-.076f},{.1125f,-.0649519053f,-.076f},
                                {0,.1299038106f,.076f},{-.1125f,-.0649519053f,.076f},{.1125f,-.0649519053f,.076f}};
    float magnitude[10206],logs[10206];float energy=0;
    unsigned clips=0;
    for(int i=0;i<10206;i++) {
        float r=X[2*i],v=X[2*i+1];
        magnitude[i]=stable_hypot(r,v);energy+=magnitude[i]*magnitude[i];
    }
    float norm=std::sqrt(energy/10206.f);if(norm<1e-6f)norm=1e-6f;
    for(int i=0;i<10206;i++) {
        float v=magnitude[i]/norm;if(v<1e-5f)v=1e-5f;
        logs[i]=std::log(v);
    }
    int pair=0;
    for(int a=0;a<6;a++)for(int b=a+1;b<6;b++) {
        float dx=mic[b][0]-mic[a][0],dy=mic[b][1]-mic[a][1],dz=mic[b][2]-mic[a][2];
        float distance=std::sqrt(dx*dx+dy*dy+dz*dz)/.225f;
        for(int f=0;f<63;f++)for(int t=0;t<27;t++) {
            int ia=(a*63+f)*27+t,ib=(b*63+f)*27+t;
            float ar=X[2*ia],ai=X[2*ia+1],br=X[2*ib],bi=X[2*ib+1];
            float re=ar*br+ai*bi,im=ai*br-ar*bi;
            float denom=stable_hypot(re,im);if(denom<1e-10f)denom=1e-10f;
            int base=pair*10206+f*27+t;
            out[base]=quantize(logs[ia],clips);out[base+1701]=quantize(logs[ib],clips);
            out[base+3402]=quantize(re/denom,clips);out[base+5103]=quantize(im/denom,clips);
            out[base+6804]=quantize((f+1)*.015625f,clips);out[base+8505]=quantize(distance,clips);
        }
        pair++;
    }
    *saturations=clips;
}
