#ifndef SIXMIC_SRPDNN_FIXED_H
#define SIXMIC_SRPDNN_FIXED_H
#include <cstdint>

enum { FIX_PAIRS=15, FIX_F=63, FIX_T=27,
       FIX_PAIR_INPUT=6*63*27, FIX_PAIR_PHASE=2*63*27,
       FIX_PAIR_SUPPORT=63*27, FIX_PAIR_HIDDEN=27*48 };

enum FixedStage {
    SAT_CONV_AFFINE, SAT_DEPTH_AFFINE, SAT_POINT_AFFINE, SAT_EMBED_AFFINE,
    SAT_GRU_INPUT_AFFINE, SAT_GRU_HIDDEN_AFFINE, SAT_GRU_RESET_PRE,
    SAT_GRU_UPDATE_PRE, SAT_GRU_NEW_PRE, SAT_GRU_HIDDEN,
    SAT_PHASE_AFFINE, SAT_SUPPORT_AFFINE, SAT_GLOBAL_MEAN,
    SAT_ACTIVITY_AFFINE, SAT_COUNT_AFFINE, SAT_STAGE_COUNT
};

struct FixedStats {
    std::uint64_t saturation[SAT_STAGE_COUNT];
    std::uint64_t nonlinear_domain_clamp[3]; // GELU, sigmoid, tanh
};

extern "C" void srpdnn_forward_fixed(
    const std::int16_t input[FIX_PAIRS*FIX_PAIR_INPUT],
    std::int16_t phase[FIX_PAIRS*FIX_PAIR_PHASE],
    std::int16_t support[FIX_PAIRS*FIX_PAIR_SUPPORT],
    std::int16_t activity[FIX_T], std::int16_t count[4], FixedStats *stats);

#endif
