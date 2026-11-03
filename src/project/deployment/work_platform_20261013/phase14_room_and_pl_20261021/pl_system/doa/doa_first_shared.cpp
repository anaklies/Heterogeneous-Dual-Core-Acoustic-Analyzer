#include <cstdint>
#include <cmath>
#include "doa_rom.h"
static float wave(float radians)
{
#pragma HLS INLINE off
    float turn=radians*.15915494309189535f;
    int whole=(int)turn;turn-=whole;if(turn<0)turn+=1;
    float pos=turn*4096;int i=(int)pos;float f=pos-i;
    if(i>=4096)i=0;
    return SINE[i]+f*(SINE[(i+1)&4095]-SINE[i]);
}
static float phase_angle(float y,float x)
{
#pragma HLS INLINE off
    float ax=std::fabs(x),ay=std::fabs(y),mx=ax>ay?ax:ay;
    if(mx==0)return 0;
    float z=(ax<ay?ax:ay)/mx,s=z*z;
    float a=z*(.99997726f+s*(-.33262347f+s*(.19354346f+s*(-.11643287f+s*(.05265332f-s*.01172120f)))));
    if(ay>ax)a=1.5707963267948966f-a;if(x<0)a=3.141592653589793f-a;
    return y<0?-a:a;
}
static float fine_score(const float v[1890],float ux,float uy,float uz,float speed)
{
#pragma HLS INLINE
    float sum=0;
    for(int p=0;p<15;p++) {
        float delay=(ux*PAIR_DELTA[p][0]+uy*PAIR_DELTA[p][1]+uz*PAIR_DELTA[p][2])/speed;
        float step=-785.3981633974483f*delay;
        float cs=wave(step+1.5707963267948966f),sn=wave(step),cr=cs,ci=sn;
        for(int f=0;f<63;f++) {
            sum+=v[(p*2)*63+f]*cr+v[(p*2+1)*63+f]*ci;
            float nr=cr*cs-ci*sn,ni=ci*cs+cr*sn;cr=nr;ci=ni;
        }
    }
    return sum/945.f;
}
// Firstdirectiononly: exactlyM'sretained output path, notthree-sourceclaims.
// Coarsetemplates inDDR areQ14 generatedatbank_speed. No truth ininference.
extern "C" void doa_first_shared(const float vector[1890],const std::int16_t bank[1160460],
    float bank_speed,float threshold,unsigned active,unsigned quality_valid,float output[9])
{
#pragma HLS ALLOCATION function instances=wave limit=1
#pragma HLS ALLOCATION function instances=phase_angle limit=1
#pragma HLS INTERFACE m_axi port=vector offset=slave bundle=observed depth=1890
#pragma HLS INTERFACE m_axi port=bank offset=slave bundle=templates depth=1160460 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=results depth=9
#pragma HLS INTERFACE s_axilite port=vector bundle=control
#pragma HLS INTERFACE s_axilite port=bank bundle=control
#pragma HLS INTERFACE s_axilite port=output bundle=control
#pragma HLS INTERFACE s_axilite port=bank_speed bundle=control
#pragma HLS INTERFACE s_axilite port=threshold bundle=control
#pragma HLS INTERFACE s_axilite port=active bundle=control
#pragma HLS INTERFACE s_axilite port=quality_valid bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for(int i=0;i<9;i++)output[i]=0;
    if(!active||!quality_valid||bank_speed<300||bank_speed>380||!std::isfinite(bank_speed)||!std::isfinite(threshold))return;
    float observed[1890];
    for(int i=0;i<1890;i++) {if(!std::isfinite(vector[i]))return;observed[i]=vector[i];}
    float best=-1e30f;int point=0;
    for(int g=0;g<614;g++) {
        float sum=0;
        for(int j=0;j<1890;j++) {
#pragma HLS PIPELINE II=4
            sum+=observed[j]*(float(bank[g*1890+j])/16384.f);
        }
        float q=sum/945.f;if(q>best){best=q;point=g;}
    }
    float ux=GRID_ROM[point][0],uy=GRID_ROM[point][1],uz=GRID_ROM[point][2];
    float coarse=best;
    for(int level=0;level<2;level++) {
        float az=phase_angle(uy,ux),el=phase_angle(uz,std::sqrt(ux*ux+uy*uy));
        int width=level==0?7:5;
        float low=level==0?-6.f:-1.f,step=level==0?2.f:.5f;
        float next_x=ux,next_y=uy,next_z=uz;
        // de isouterindex, da isinnerindex, as NumPy'smeshgrid flattenorder.
        for(int ie=0;ie<width;ie++)for(int ia=0;ia<width;ia++) {
            float a=az+(low+ia*step)*.017453292519943295f;
            float e=el+(low+ie*step)*.017453292519943295f;
            float ce=wave(e+1.5707963267948966f);
            float x=ce*wave(a+1.5707963267948966f),y=ce*wave(a),z=wave(e);
            float q=fine_score(observed,x,y,z,bank_speed);
            if(q>best){best=q;next_x=x;next_y=y;next_z=z;}
        }
        ux=next_x;uy=next_y;uz=next_z;
    }
    output[0]=best>=threshold;output[1]=best;
    output[2]=ux;output[3]=uy;output[4]=uz;
    output[5]=phase_angle(uy,ux)*57.29577951308232f;
    output[6]=phase_angle(uz,std::sqrt(ux*ux+uy*uy))*57.29577951308232f;
    output[7]=coarse;output[8]=point; // pointID isNOTtrackID.
}
