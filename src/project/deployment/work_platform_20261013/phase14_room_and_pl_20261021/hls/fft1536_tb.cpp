#include <cmath>
#include <cstdio>
extern "C" void fft1536_vendor(const float*,float*);
int main()
{
    float input[1536],output[1538];
    for(int test=0;test<2;test++) {
        for(int n=0;n<1536;n++) input[n]=test==0?(n==333?.1f:0.f):.02f*std::sin(2*3.141592653589793*37*n/1536);
        fft1536_vendor(input,output);
        double maximum=0;
        for(int k=0;k<=768;k++) {
            double re=0,im=0;
            for(int n=0;n<1536;n++) {
                double value=input[n]*(.5-.5*std::cos(2*3.141592653589793*n/1536));
                re+=value*std::cos(2*3.141592653589793*k*n/1536);
                im-=value*std::sin(2*3.141592653589793*k*n/1536);
            }
            double error=std::hypot(re-output[2*k],im-output[2*k+1]);
            maximum=std::fmax(maximum,error);
        }
        std::printf("FFT1536_VENDOR_CASE%d_MAXERROR %.9g\n",test,maximum);
        if(maximum>1e-4) return 1;
    }
    std::puts("FFT1536_VENDOR_NUMERIC_PASS1538bins");return 0;
}
