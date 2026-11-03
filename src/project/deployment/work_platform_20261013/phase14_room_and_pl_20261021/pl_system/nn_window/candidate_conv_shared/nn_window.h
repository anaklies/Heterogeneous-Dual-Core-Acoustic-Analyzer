#ifndef SIXMIC_NN_WINDOW_H
#define SIXMIC_NN_WINDOW_H
#include <cstdint>
enum { WINDOW_INPUT=153090, WINDOW_PHASE=51030, WINDOW_SUPPORT=25515,
       WINDOW_LOGITS=31, WINDOW_VECTOR=1890, WINDOW_COUNTERS=18, WINDOW_META=5 };
// InputQ11; phaseQ13; support/activity/countlogitsQ10. Vectorfloat32 is normalized
// as63*sum(phaseQ13*weightQ15)/(8192*massQ15). Metadata: massQ15, activityQ15, activeflag,
// effectiveTFcount and nonlinearclamps added by the aggregation stage.
extern "C" void nn_window(const std::int16_t input[WINDOW_INPUT],
    std::int16_t phase[WINDOW_PHASE], std::int16_t support[WINDOW_SUPPORT],
    std::int16_t logits[WINDOW_LOGITS], float vector[WINDOW_VECTOR],
    std::uint64_t metadata[WINDOW_META], std::uint64_t counters[WINDOW_COUNTERS]);
#endif
