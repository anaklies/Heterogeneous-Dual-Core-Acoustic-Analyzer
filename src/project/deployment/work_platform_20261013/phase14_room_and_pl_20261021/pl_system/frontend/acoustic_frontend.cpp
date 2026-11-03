#include "acoustic_frontend.h"
#include <cmath>
// Reuse the accepted FFT arithmetic, geometry and fixed point contract.
#include "../../hls/fft1536_burst_vendor.cpp"
using namespace sixmic_frontend;

static float safe_magnitude(float x,float y)
{
    float ax=std::fabs(x),ay=std::fabs(y),m=ax>ay?ax:ay;
    if(m==0)return 0;
    x/=m;y/=m;
    return m*std::sqrt(x*x+y*y);
}

static std::int16_t to_q11(float x,unsigned &clips)
{
    float scaled=x*2048.f;
    if(scaled>32767){++clips;return 32767;}
    if(scaled< -32768){++clips;return -32768;}
    int q=(int)scaled;
    float fraction=std::fabs(scaled-q);
    if(fraction>.5f||(fraction==.5f&&(q&1)))q+=scaled>=0?1:-1;
    return std::int16_t(q);
}

extern "C" void acoustic_frontend(const std::int32_t pcm[70656],
    const float previous[20412],const std::uint32_t previous_meta[16],
    float current[20412],float scratch[10206],std::int16_t features[153090],
    std::uint32_t meta[16],std::uint64_t start_sample,
    std::uint32_t config,std::uint32_t session,unsigned allow_reuse)
{
#pragma HLS INTERFACE m_axi port=pcm offset=slave bundle=audio depth=70656 num_read_outstanding=2 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=previous offset=slave bundle=cache depth=20412 num_read_outstanding=2 num_write_outstanding=2 max_read_burst_length=64 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=previous_meta offset=slave bundle=cache depth=16
#pragma HLS INTERFACE m_axi port=current offset=slave bundle=cache depth=20412
#pragma HLS INTERFACE m_axi port=scratch offset=slave bundle=cache depth=10206
#pragma HLS INTERFACE m_axi port=features offset=slave bundle=features depth=153090 num_write_outstanding=2 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=meta offset=slave bundle=results depth=16 num_write_outstanding=2 max_write_burst_length=16
#pragma HLS INTERFACE s_axilite port=pcm bundle=control
#pragma HLS INTERFACE s_axilite port=previous bundle=control
#pragma HLS INTERFACE s_axilite port=previous_meta bundle=control
#pragma HLS INTERFACE s_axilite port=current bundle=control
#pragma HLS INTERFACE s_axilite port=scratch bundle=control
#pragma HLS INTERFACE s_axilite port=features bundle=control
#pragma HLS INTERFACE s_axilite port=meta bundle=control
#pragma HLS INTERFACE s_axilite port=start_sample bundle=control
#pragma HLS INTERFACE s_axilite port=config bundle=control
#pragma HLS INTERFACE s_axilite port=session bundle=control
#pragma HLS INTERFACE s_axilite port=allow_reuse bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION function instances=fft1536_burst_vendor limit=1
    // Invalid until all writes complete and the dispatcher accepts ap_done
    // with no AXI response error. A commit word alone is not a bus fence.
    for(int i=0;i<16;i++)meta[i]=0;
    meta[VERSION]=ABI;meta[CONFIG]=config;meta[SESSION]=session;
    meta[START_LO]=std::uint32_t(start_sample);
    meta[START_HI]=std::uint32_t(start_sample>>32);
    meta[NFFT]=FFT;meta[HOP_SIZE]=HOP;meta[TIME_COUNT]=TIMES;meta[BIN_COUNT]=BINS;
    if(start_sample>UINT64_MAX-WINDOW){meta[ERROR]=SAMPLE_ID_OVERFLOW;return;}

    std::uint64_t old_start=std::uint64_t(previous_meta[START_HI])<<32 |
                            previous_meta[START_LO];
    bool reuse=allow_reuse && previous_meta[COMMIT]==MAGIC &&
        previous_meta[VERSION]==ABI && previous_meta[CONFIG]==config &&
        previous_meta[SESSION]==session && previous_meta[ERROR]==NONE &&
        previous_meta[NFFT]==FFT && previous_meta[HOP_SIZE]==HOP &&
        previous_meta[TIME_COUNT]==TIMES && previous_meta[BIN_COUNT]==BINS &&
        old_start<=UINT64_MAX-ADVANCE && old_start+ADVANCE==start_sample;
    meta[MODE]=reuse?1:0;
    if(reuse) {
        for(int ch=0;ch<CHANNELS;ch++)for(int f=0;f<BINS;f++)
            for(int t=0;t<TIMES-NEW_TIMES;t++) {
#pragma HLS PIPELINE II=2
                int to=((ch*BINS+f)*TIMES+t)*2;
                int from=((ch*BINS+f)*TIMES+t+NEW_TIMES)*2;
                current[to]=previous[from];current[to+1]=previous[from+1];
            }
        meta[REUSED]=CHANNELS*(TIMES-NEW_TIMES);
    }
    std::int32_t samples[FFT];float transformed[2*(FFT/2+1)];
    for(int ch=0;ch<CHANNELS;ch++)for(int t=0;t<TIMES;t++) {
        if(reuse && t<TIMES-NEW_TIMES)continue;
        for(int n=0;n<FFT;n++) {
#pragma HLS PIPELINE II=1
            std::int32_t v=pcm[(t*HOP+n)*CHANNELS+ch];
            if(v< -8388608 || v>8388607){meta[ERROR]=BAD_PCM;return;}
            samples[n]=v;
        }
        fft1536_burst_vendor(samples,transformed);
        for(int f=0;f<BINS;f++) {
#pragma HLS PIPELINE II=2
            int at=((ch*BINS+f)*TIMES+t)*2,bin=(f+1)*4;
            current[at]=transformed[2*bin];current[at+1]=transformed[2*bin+1];
        }
        ++meta[COMPUTED];
    }

    // This scratch array is an explicit DDR argument. Do not allocate two
    // 40KiB magnitude/log arrays inside the PL as in the software reference.
    float energy=0;
    for(int i=0;i<10206;i++) {
        float r=current[2*i],v=current[2*i+1];
        if(!std::isfinite(r)||!std::isfinite(v)){
            meta[ERROR]=NONFINITE_SPECTRUM;return;
        }
        float magnitude=safe_magnitude(r,v);
        scratch[i]=magnitude;energy+=magnitude*magnitude;
    }
    float norm=std::sqrt(energy/10206.f);if(norm<1e-6f)norm=1e-6f;
    for(int i=0;i<10206;i++) {
        float v=scratch[i]/norm;if(v<1e-5f)v=1e-5f;
        scratch[i]=std::log(v);
    }
    static const float mic[6][3]={{0,.1299038106f,-.076f},{-.1125f,-.0649519053f,-.076f},
        {.1125f,-.0649519053f,-.076f},{0,.1299038106f,.076f},
        {-.1125f,-.0649519053f,.076f},{.1125f,-.0649519053f,.076f}};
    unsigned clips=0;int pair=0;
    for(int a=0;a<6;a++)for(int b=a+1;b<6;b++) {
        float dx=mic[b][0]-mic[a][0],dy=mic[b][1]-mic[a][1],dz=mic[b][2]-mic[a][2];
        float distance=std::sqrt(dx*dx+dy*dy+dz*dz)/.225f;
        for(int f=0;f<BINS;f++)for(int t=0;t<TIMES;t++) {
            int ia=(a*BINS+f)*TIMES+t,ib=(b*BINS+f)*TIMES+t;
            float ar=current[2*ia],ai=current[2*ia+1],br=current[2*ib],bi=current[2*ib+1];
            float re=ar*br+ai*bi,im=ai*br-ar*bi;
            float denominator=safe_magnitude(re,im);
            if(denominator<1e-10f)denominator=1e-10f;
            int base=pair*10206+f*TIMES+t;
            features[base]=to_q11(scratch[ia],clips);
            features[base+1701]=to_q11(scratch[ib],clips);
            features[base+3402]=to_q11(re/denominator,clips);
            features[base+5103]=to_q11(im/denominator,clips);
            features[base+6804]=to_q11((f+1)*.015625f,clips);
            features[base+8505]=to_q11(distance,clips);
        }
        ++pair;
    }
    meta[SATURATIONS]=clips;
    if(clips){meta[ERROR]=FEATURE_CLIP;return;}
    meta[COMMIT]=MAGIC;
}
