#include "srpdnn_fixed.cpp"
#include <cmath>
#include <cstdio>

int main()
{
    unsigned long long checks=0;
    for (i64 v=-65536;v<=65536;++v)
        for (int shift=0;shift<=15;++shift) {
            const i64 magnitude=v>=0?v:-v;
            const i64 divisor=i64(1)<<shift;
            i64 q=magnitude/divisor;
            if (shift && magnitude%divisor>=divisor/2) ++q;
            const i64 expected=v>=0?q:-q;
            if (round_shift(v,shift)!=expected) return 1;
            ++checks;
        }
    FixedStats s={};
    double gelu_error=0,sigmoid_error=0,tanh_error=0;
    i32 previous_sigmoid=-1,previous_tanh=-32769;
    for (int value=-32768;value<=32767;++value) {
        const double x=value/1024.0;
        const double g=0.5*x*(1+std::erf(x/std::sqrt(2.0)));
        const double sig=1.0/(1+std::exp(-x));
        const double th=std::tanh(x);
        const i32 gi=gelu(i16(value),&s),si=sigmoid(i16(value),&s),ti=tanh_q14(i16(value),&s);
        gelu_error=std::fmax(gelu_error,std::abs(gi/1024.0-g));
        sigmoid_error=std::fmax(sigmoid_error,std::abs(si/32768.0-sig));
        tanh_error=std::fmax(tanh_error,std::abs(ti/16384.0-th));
        if (si<previous_sigmoid || ti<previous_tanh) return 2;
        previous_sigmoid=si;previous_tanh=ti;
        ++checks;
    }
    if (gelu_error>.0011 || sigmoid_error>.0004 || tanh_error>.00007) return 3;
    std::printf("{\"integerChecks\":%llu,\"GELUMaxAbsoluteError\":%.12g,\"sigmoidMaxAbsoluteError\":%.12g,\"tanhMaxAbsoluteError\":%.12g,\"status\":\"PASS\"}\n",
        checks,gelu_error,sigmoid_error,tanh_error);
    return 0;
}
