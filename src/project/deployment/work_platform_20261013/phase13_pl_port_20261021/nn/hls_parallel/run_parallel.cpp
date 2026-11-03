#include "../fixed/srpdnn_fixed.h"
extern "C" void srpdnn_forward_parallel(const std::int16_t*,std::int16_t*,std::int16_t*,std::int16_t*,std::int16_t*,FixedStats*);
#include <cstdio>

static std::int16_t input[FIX_PAIRS*FIX_PAIR_INPUT];
static std::int16_t phase[FIX_PAIRS*FIX_PAIR_PHASE];
static std::int16_t support[FIX_PAIRS*FIX_PAIR_SUPPORT];
static std::int16_t activity[27],count[4];

int main(int argc,char **argv)
{
    if (argc!=4) return 2;
    FILE *f=std::fopen(argv[1],"rb");
    if (!f) return 3;
    const size_t n=std::fread(input,sizeof(input[0]),FIX_PAIRS*FIX_PAIR_INPUT,f);
    const int extra=std::fgetc(f);
    std::fclose(f);
    if (n!=FIX_PAIRS*FIX_PAIR_INPUT || extra!=EOF) return 4;
    FixedStats stats;
    srpdnn_forward_parallel(input,phase,support,activity,count,&stats);
    f=std::fopen(argv[2],"wb");
    if (!f) return 5;
    const bool ok=std::fwrite(phase,sizeof(phase[0]),FIX_PAIRS*FIX_PAIR_PHASE,f)==FIX_PAIRS*FIX_PAIR_PHASE
        && std::fwrite(support,sizeof(support[0]),FIX_PAIRS*FIX_PAIR_SUPPORT,f)==FIX_PAIRS*FIX_PAIR_SUPPORT
        && std::fwrite(activity,sizeof(activity[0]),27,f)==27
        && std::fwrite(count,sizeof(count[0]),4,f)==4;
    if (std::fclose(f) || !ok) return 6;
    f=std::fopen(argv[3],"wb");
    if (!f) return 7;
    for (int i=0;i<SAT_STAGE_COUNT;++i)
        std::fprintf(f,"%llu\n",(unsigned long long)stats.saturation[i]);
    for (int i=0;i<3;++i)
        std::fprintf(f,"%llu\n",(unsigned long long)stats.nonlinear_domain_clamp[i]);
    return std::fclose(f) ? 8 : 0;
}
