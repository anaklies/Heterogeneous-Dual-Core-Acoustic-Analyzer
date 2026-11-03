#include "../../fixed/srpdnn_fixed.cpp"
extern "C" void golden_pair(const i16 *input,i16 *output,std::uint64_t *counters)
{
    FixedStats stats={};
    pair_forward(input,output,output+FIX_PAIR_PHASE,output+FIX_PAIR_PHASE+FIX_PAIR_SUPPORT,&stats);
    for(int i=0;i<SAT_STAGE_COUNT;i++)counters[i]=stats.saturation[i];
    for(int i=0;i<3;i++)counters[SAT_STAGE_COUNT+i]=stats.nonlinear_domain_clamp[i];
}
