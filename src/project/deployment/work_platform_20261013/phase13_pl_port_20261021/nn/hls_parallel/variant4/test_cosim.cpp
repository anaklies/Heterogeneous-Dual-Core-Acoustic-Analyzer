#include <cstdint>
#include <cstdio>
extern "C" void golden_pair(const std::int16_t*,std::int16_t*,std::uint64_t*);
extern "C" void nn_parallel_v4(const std::int16_t*,std::int16_t*,std::uint64_t*);
static std::int16_t input[10206],expected[6399],actual[6399];
static std::uint64_t before[18],after[18];
int main()
{
    // One already-frozen firstpair; no newPCM or acousticparameter selection.
    FILE *f=std::fopen("C:/Users/sunxi/Desktop/sixmic3D/deployment/work_platform_20261013/phase13_pl_port_20261021/nn/fixed/room0_speech_input_q11.bin","rb");
    if(!f)return 2;
    size_t n=std::fread(input,sizeof(input[0]),10206,f);std::fclose(f);
    if(n!=10206)return 3;
    golden_pair(input,expected,before);
    nn_parallel_v4(input,actual,after);
    unsigned failures=0;
    for(int i=0;i<6399;i++)if(actual[i]!=expected[i])failures++;
    for(int i=0;i<18;i++)if(after[i]!=before[i])failures++;
    std::printf("NN_V4_ONEPAIR_EQUIVALENCE values=6399 counters=18 failures=%u\n",failures);
    return failures?1:0;
}
