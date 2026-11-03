// Additional shared scalar stages. These stages are not whole product services.
static void extended_compute(ReadPort &a,ReadPort &b,WritePort &out,unsigned n,unsigned frames,
    unsigned operation,float df,float parameter,unsigned *status)
{
#pragma HLS INLINE
    *status=0;
    if(!n||n>262144||frames>32||!isfinite(df)||df<1.e-6f||df>192000||!isfinite(parameter)){*status=1;return;}
    unsigned na=n,nb=0,no=n;
    if(operation==14)nb=n;
    else if(operation==15){nb=n;no=2*n;}
    else if(operation==16){nb=frames;no=3*frames+2;if(!frames||parameter<=0){*status=16;return;}}
    else if(operation==17){no=2*n;if(parameter<0){*status=17;return;}}
    else if(operation==18)no=8;
    else if(operation==19){nb=2;no=6;if(parameter<0||parameter>1){*status=19;return;}}
    else if(operation==20){nb=3;no=4;}
    else {*status=255;return;}
    if(no>262144||!a.length(na)||!b.length(nb)||!out.length(no)){*status=14;return;}
    for(unsigned i=0;i<na;i++)if(!isfinite(a.get(i))){*status=15;return;}
    for(unsigned i=0;i<nb;i++)if(!isfinite(b.get(i))){*status=15;return;}
    if(operation==14) {
        for(unsigned i=0;i<n;i++) {
            if(a.get(i)<0||b.get(i)<0){*status=14;return;}
            out.put(i,fmaxf(a.get(i),b.get(i)));
        }
    } else if(operation==15) {
        // Invalid first drift is accompanied by a zero valid flag.
        for(unsigned i=1;i<n;i++)if(b.get(i)<=b.get(i-1)){*status=15;return;}
        for(unsigned i=0;i<n;i++) {
            out.put(2*i,i?(a.get(i)-a.get(i-1))/(b.get(i)-b.get(i-1)):0);
            out.put(2*i+1,i?1:0);
        }
    } else if(operation==16) {
        // PSD bins are nonnegative FS2/Hz. Each center is user supplied.
        for(unsigned i=0;i<n;i++)if(a.get(i)<0){*status=16;return;}
        float first=0,other=0;
        for(unsigned h=0;h<frames;h++) {
            float center=b.get(h),energy=0,peak=-1;unsigned best=0;
            if(center<0||center>(n-1)*df){*status=16;return;}
            for(unsigned k=0;k<n;k++)if(fabsf(k*df-center)<=parameter) {
                float power=a.get(k);energy+=power*df;
                if(power>peak){peak=power;best=k;}
            }
            if(h==0)first=energy;else other+=energy;
            out.put(3*h,best*df);out.put(3*h+1,energy);
            out.put(3*h+2,first>0?energy/first:0);
        }
        out.put(3*frames,first>0?sqrtf(other/first):0);
        out.put(3*frames+1,first>0?1:0);
    } else if(operation==17) {
        // Input is an onset-aligned IR. Caller estimates stationary noise floor.
        // Reverse accumulation preserves the quiet tail. Subtracting each early
        // sample from a large forward total destroys low-level decay in float32.
        float energy=0;
        for(unsigned j=0;j<n;j++) {
            unsigned i=n-1-j;float v=a.get(i);energy+=v*v;
            out.put(2*i,fmaxf(0,energy-parameter*(n-i)));
        }
        float initial=out.get(0);
        if(initial<=0||!isfinite(initial)){*status=17;return;}
        float previous=initial;
        for(unsigned i=0;i<n;i++) {
            float corrected=fminf(previous,out.get(2*i));
            out.put(2*i,corrected);
            out.put(2*i+1,10*log10f(fmaxf(corrected/initial,1.e-30f)));
            previous=corrected;
        }
    } else if(operation==18) {
        // Caller must align IR onset. No room/arrival inference is performed.
        if(n<.08f*df){*status=18;return;}
        float total=0,early50=0,early80=0,late50=0,late80=0;
        for(unsigned i=0;i<n;i++) {
            float v=a.get(i),p=v*v;total+=p;
            if(i<.05f*df)early50+=p;else late50+=p;
            if(i<.08f*df)early80+=p;else late80+=p;
        }
        out.put(0,total>0&&early50>0&&late50>0?10*log10f(early50/late50):0);
        out.put(1,total>0&&early80>0&&late80>0?10*log10f(early80/late80):0);
        out.put(2,total>0?early50/total:0);
        out.put(3,early50>0&&late50>0);out.put(4,early80>0&&late80>0);
        out.put(5,total>0);out.put(6,total);out.put(7,n/df);
    } else if(operation==19) {
        float upper=b.get(0),lower=b.get(1);
        if(upper<=lower){*status=19;return;}
        unsigned count=0,first=0,last=0;bool reaches=false;
        float tx=0,ty=0;
        for(unsigned i=0;i<n;i++) {
            float v=a.get(i);if(v<=lower)reaches=true;
            if(v>=lower&&v<=upper){if(!count)first=i;last=i;++count;tx+=i/df;ty+=v;}
        }
        float mx=count?tx/count:0,my=count?ty/count:0,sxx=0,sxy=0,syy=0;
        for(unsigned i=0;i<n;i++) {
            float v=a.get(i);
            if(v>=lower&&v<=upper){float x=i/df-mx,y=v-my;sxx+=x*x;sxy+=x*y;syy+=y*y;}
        }
        float slope=sxx>0?sxy/sxx:0;
        float r2=sxx>0&&syy>0?fminf(1.f,sxy*sxy/(sxx*syy)):0;
        float duration=(last-first)/df;
        bool valid=reaches&&count>=16&&duration>=.005f&&slope<0&&r2>=parameter;
        out.put(0,valid?-60/slope:0);out.put(1,slope);out.put(2,r2);
        out.put(3,count);out.put(4,valid);out.put(5,duration);
    } else if(operation==20) {
        // Same normalized autocorrelation and first-near-best peak policy.
        float min_hz=b.get(0),max_hz=b.get(1),threshold=b.get(2);
        if(min_hz<=0||max_hz<=min_hz||max_hz>=df*.5f||threshold<=0||threshold>=1||n<4||min_hz<df/(n-2)){*status=20;return;}
        unsigned lo=(unsigned)ceilf(df/max_hz),hi=(unsigned)(df/min_hz);
        if(hi+1>=n||hi<=lo){*status=20;return;}
        float best=0;
        for(unsigned i=lo;i<=hi;i++)if(a.get(i)>a.get(i-1)&&a.get(i)>=a.get(i+1))best=fmaxf(best,a.get(i));
        unsigned chosen=0;
        for(unsigned i=lo;i<=hi;i++)if(!chosen&&a.get(i)>a.get(i-1)&&a.get(i)>=a.get(i+1)&&a.get(i)>=fmaxf(threshold,best-.03f))chosen=i;
        float delta=0;
        if(chosen){float l=a.get(chosen-1),m=a.get(chosen),r=a.get(chosen+1),den=l-2*m+r;if(den<0)delta=fmaxf(-.5f,fminf(.5f,.5f*(l-r)/den));}
        out.put(0,chosen?fmaxf(min_hz,fminf(max_hz,df/(chosen+delta))):0);
        out.put(1,chosen?chosen+delta:0);out.put(2,chosen?a.get(chosen):best);out.put(3,chosen?1:0);
    }
}
