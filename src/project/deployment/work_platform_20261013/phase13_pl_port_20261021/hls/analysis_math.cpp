#include <math.h>
#include <stdint.h>
// Bounded minimax atan polynomial avoids the vendorCORDIC library's dynamic
// table initializer on this WindowsHLS toolchain. Inputdata is checked finite.
static float phase_angle(float y,float x)
{
    float ax=fabsf(x),ay=fabsf(y);
    if(ax==0&&ay==0)return 0;
    float z=fminf(ax,ay)/fmaxf(ax,ay),s=z*z;
    float angle=z*(.99997726f+s*(-.33262347f+s*(.19354346f+s*(-.11643287f+s*(.05265332f-s*.01172120f)))));
    if(ay>ax)angle=1.5707963267948966f-angle;
    if(x<0)angle=3.1415926535897932f-angle;
    return y<0?-angle:angle;
}
// Shared mathematical primitives. Lengths are bounded and each call is finite.
// The frame scheduler/DDR owner must provide coherent complete input arrays.
// This does NOT implement the absent FFT/NN system scheduler by itself.
extern "C" void analysis_math(const float *a,const float *b,float *out,
    unsigned n,unsigned frames,unsigned operation,float df,float parameter,unsigned *status)
{
#pragma HLS INTERFACE m_axi port=a offset=slave bundle=audio depth=262144
#pragma HLS INTERFACE m_axi port=b offset=slave bundle=audio depth=262144
#pragma HLS INTERFACE m_axi port=out offset=slave bundle=results depth=262144
#pragma HLS INTERFACE s_axilite port=a bundle=control
#pragma HLS INTERFACE s_axilite port=b bundle=control
#pragma HLS INTERFACE s_axilite port=out bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=frames bundle=control
#pragma HLS INTERFACE s_axilite port=operation bundle=control
#pragma HLS INTERFACE s_axilite port=df bundle=control
#pragma HLS INTERFACE s_axilite port=parameter bundle=control
#pragma HLS INTERFACE s_axilite port=status bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    *status=0;
    if(n==0||n>32768||frames>1024||df<=0||!isfinite(df)||!isfinite(parameter)){*status=1;return;}
    unsigned na=n,nb=0,no=n;
    switch(operation) {
        case 1:na=6*n;no=48;break;
        case 2:na=n+2;no=3*(n/2+1);break;
        case 3:no=6;break;
        case 5:na=2*n*frames;nb=na;no=7*n;break;
        case 6:nb=n;no=4;break;
        case 7:na=n*frames;no=2*n;break;
        case 8:nb=2*frames;no=3*frames;break;
        case 9:no=frames+2;break;
        case 10:na=12*n*frames;nb=12*n;break;
        case 11:nb=n;no=2*n;break;
        case 12:nb=2*n;no=2*n;break;
        case 13:na=2*n;break;
        case 4:break;
        default:*status=255;return;
    }
    if(na>262144||nb>262144||no>262144){*status=14;return;}
    for(unsigned i=0;i<na;i++)if(!isfinite(a[i])){*status=15;return;}
    for(unsigned i=0;i<nb;i++)if(!isfinite(b[i])){*status=15;return;}
    if(operation==1) {
        // n samples x6 normalized channels. Eight fields/channel.
        for(unsigned c=0;c<6;c++) {
            float sum=0,square=0,peak=0,lo=1.e30f,hi=-1.e30f;unsigned clips=0;
            for(unsigned i=0;i<n;i++) {
                float x=a[i*6+c];sum+=x;square+=x*x;peak=fmaxf(peak,fabsf(x));lo=fminf(lo,x);hi=fmaxf(hi,x);
                clips+=(x<=-1.f||x>=8388607.f/8388608.f);
            }
            float rms=sqrtf(square/n);
            out[c*8]=rms;out[c*8+1]=peak;out[c*8+2]=hi-lo;out[c*8+3]=sum/n;
            out[c*8+4]=rms>0?20*log10f(rms):0;
            out[c*8+5]=rms>0?peak/rms:0;out[c*8+6]=clips;out[c*8+7]=rms>0;
        }
    } else if(operation==2) {
        // n=FFT length, input interleaved complex one-sided unscaled Hann FFT.
        if(n<4||n%2){*status=2;return;}
        float fs=df*n,wsum=n*.5f,wenergy=n*.375f;
        for(unsigned k=0;k<=n/2;k++) {
            float re=a[2*k],im=a[2*k+1],p=re*re+im*im,one=(k==0||k==n/2)?1.f:2.f;
            out[3*k]=sqrtf(p)*one/wsum;out[3*k+1]=p*one/(fs*wenergy);out[3*k+2]=out[3*k+1]*df;
        }
    } else if(operation==3) {
        float sum=0,weighted=0,logsum=0,peak=-1;unsigned best=0;bool positive=true;
        for(unsigned i=0;i<n;i++) {
            float x=a[i];if(!isfinite(x)||x<0){*status=3;return;}
            sum+=x;weighted+=x*(i*df);positive=positive&&x>0;
            if(x>0)logsum+=logf(x);
            if(i>0&&x>peak){peak=x;best=i;}
        }
        float delta=0;
        if(best>0&&best+1<n&&a[best-1]>0&&a[best]>0&&a[best+1]>0) {
            float l=logf(a[best-1]),m=logf(a[best]),r=logf(a[best+1]),den=l-2*m+r;
            if(den<0)delta=fmaxf(-.5f,fminf(.5f,.5f*(l-r)/den));
        }
        out[0]=sum*df;out[1]=sum>0?weighted/sum:0;
        out[2]=sum>0&&positive?expf(logsum/n)/(sum/n):0;
        out[3]=(best+delta)*df;out[4]=fmaxf(peak,0);out[5]=sum>0;
    } else if(operation==4) {
        unsigned width=(unsigned)parameter;
        if(width<1||width>n||width%2==0||width!=parameter){*status=4;return;}
        for(unsigned i=0;i<n;i++) {
            float sum=0;unsigned count=0;
            for(unsigned j=0;j<width;j++) {
                int k=(int)i+(int)j-(int)width/2;
                if(k>=0&&(unsigned)k<n){sum+=a[k];count++;}
            }
            out[i]=sum/count;
        }
    } else if(operation==5) {
        // Independent frames, two complex channels, b=secondchannel. SciPyconj(Xi)Xj.
        if(frames<2){*status=5;return;}
        for(unsigned k=0;k<n;k++) {
            float cr=0,ci=0,pi=0,pj=0;
            for(unsigned t=0;t<frames;t++) {
                unsigned j=2*(t*n+k);float ar=a[j],ai=a[j+1],br=b[j],bi=b[j+1];
                cr+=ar*br+ai*bi;ci+=ar*bi-ai*br;pi+=ar*ar+ai*ai;pj+=br*br+bi*bi;
            }
            float scale=parameter/frames;
            out[k*7]=cr*scale;out[k*7+1]=ci*scale;out[k*7+2]=pi*scale;out[k*7+3]=pj*scale;
            out[k*7+4]=pi>0&&pj>0?fminf(1.f,fmaxf(0.f,(cr*cr+ci*ci)/(pi*pj))):0;
            out[k*7+5]=phase_angle(ci,cr);out[k*7+6]=pi>0&&pj>0;
        }
    } else if(operation==6) {
        float ea=0,eb=0,flux=0;
        for(unsigned i=0;i<n;i++){ea+=a[i];eb+=b[i];}
        for(unsigned i=0;i<n;i++) {
            float d=fmaxf(0.f,(eb>0?b[i]/eb:0)-(ea>0?a[i]/ea:0));flux+=d*d;
        }
        out[0]=eb;out[1]=eb-ea;out[2]=sqrtf(flux);out[3]=ea>0;
    } else if(operation==7) {
        if(frames<3){*status=7;return;}
        for(unsigned k=0;k<n;k++) {
            float s=0,s2=0;
            for(unsigned t=0;t<frames;t++){float x=a[t*n+k];s+=x;s2+=x*x;}
            out[k*2]=s>0?(frames+1.f)/(frames-1.f)*(frames*s2/(s*s)-1.f)-1.f:0;
            out[k*2+1]=s>0;
        }
    } else if(operation==8) {
        // b holds frames low/high Hz pairs foroctave/user-definedbands.
        for(unsigned band=0;band<frames;band++) {
            float low=b[2*band],high=b[2*band+1],sum=0;unsigned bins=0;
            if(low<0||high<=low){*status=8;return;}
            for(unsigned k=0;k<n;k++) if(k*df>=low&&(k*df<high||(k==n-1&&high>=k*df))){sum+=a[k];bins++;}
            out[band*3]=sum*df;out[band*3+1]=bins;out[band*3+2]=bins>=2;
        }
    } else if(operation==9) {
        // Direct mean-removed normalized biased autocorrelation, includinglag0.
        // Long calls must be split/yielded by the integration scheduler.
        if(frames>=n){*status=9;return;}
        float mean=0,zero=0;for(unsigned i=0;i<n;i++)mean+=a[i];mean/=n;
        for(unsigned i=0;i<n;i++){float x=a[i]-mean;zero+=x*x;}
        for(unsigned lag=0;lag<=frames;lag++) {
            float sum=0;for(unsigned i=0;i<n-lag;i++)sum+=(a[i]-mean)*(a[i+lag]-mean);
            out[lag]=zero>0?sum/zero:0;
        }
        out[frames+1]=zero>0;
    } else if(operation==10) {
        // a:frame xfrequency x6 complex. b:frequency x6 already-normalized DAS weights.
        if(frames<1){*status=10;return;}
        for(unsigned k=0;k<n;k++) {
            float power=0;
            for(unsigned t=0;t<frames;t++) {
                float sr=0,si=0;
                for(unsigned c=0;c<6;c++) {
                    unsigned j=2*((t*n+k)*6+c),w=2*(k*6+c);
                    sr+=b[w]*a[j]+b[w+1]*a[j+1];si+=b[w]*a[j+1]-b[w+1]*a[j];
                }
                power+=sr*sr+si*si;
            }
            out[k]=power*parameter/frames;
        }
    } else if(operation==11) {
        // Same-grid reference comparison; caller must enforce metadata equality.
        for(unsigned k=0;k<n;k++) {
            out[k*2]=a[k]>0&&b[k]>0?10*log10f(b[k]/a[k]):0;
            out[k*2+1]=a[k]>0&&b[k]>0;
        }
    } else if(operation==12) {
        // Existing sum+new-minus-old exact sliding update. Inputs a=sum,b=[new,old].
        if(frames<1){*status=12;return;}
        for(unsigned k=0;k<n;k++){float s=a[k]+b[k]-b[n+k];out[2*k]=s;out[2*k+1]=s/frames;}
    } else if(operation==13) {
        // Analytic-signal magnitude AFTER the correctly paddedFFT/IFFT Hilbertstage.
        for(unsigned k=0;k<n;k++)out[k]=sqrtf(a[2*k]*a[2*k]+a[2*k+1]*a[2*k+1]);
    } else *status=255;
}
