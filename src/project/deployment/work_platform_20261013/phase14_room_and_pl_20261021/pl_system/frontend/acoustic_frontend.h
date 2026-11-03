#ifndef SIXMIC_ACOUSTIC_FRONTEND_H
#define SIXMIC_ACOUSTIC_FRONTEND_H
#include <cstdint>
namespace sixmic_frontend {
constexpr int CHANNELS=6, WINDOW=11776, FFT=1536, HOP=384;
constexpr int TIMES=27, BINS=63, ADVANCE=4608, NEW_TIMES=12;
constexpr int CACHE_FLOATS=CHANNELS*BINS*TIMES*2;
constexpr int FEATURE_WORDS=15*6*BINS*TIMES;
constexpr unsigned MAGIC=0x53464631, ABI=1;
enum Meta { COMMIT=0, VERSION=1, CONFIG=2, SESSION=3, START_LO=4,
            START_HI=5, NFFT=6, HOP_SIZE=7, TIME_COUNT=8, BIN_COUNT=9,
            COMPUTED=10, REUSED=11, SATURATIONS=12, ERROR=13,
            MODE=14, RESERVED=15 };
enum Error { NONE=0, BAD_PCM=1, NONFINITE_SPECTRUM=2,
             FEATURE_CLIP=4, SAMPLE_ID_OVERFLOW=8 };
}
// PCM is interleaved signed24 in signed32. All cache/scratch/features live in
// a reserved DMA-safe DDR arena, not ordinary process virtual memory.
// A dispatcher must keep each input immutable until completion. Previous and
// current cache, descriptors, PCM, scratch and output regions must not alias.
extern "C" void acoustic_frontend(const std::int32_t pcm[70656],
    const float previous[20412],const std::uint32_t previous_meta[16],
    float current[20412],float scratch[10206],std::int16_t features[153090],
    std::uint32_t meta[16],std::uint64_t start_sample,
    std::uint32_t config,std::uint32_t session,unsigned allow_reuse);
// Selected candidate has an additional20KiB DDR log-quantization workspace.
// Cache layout and metadata ABI are identical to the baseline frontend.
extern "C" void acoustic_frontend_pipeline(const std::int32_t pcm[70656],
    const float previous[20412],const std::uint32_t previous_meta[16],
    float current[20412],float scratch[10206],std::int16_t qlogs[10206],
    std::int16_t features[153090],std::uint32_t meta[16],
    std::uint64_t start_sample,std::uint32_t config,std::uint32_t session,
    unsigned allow_reuse);
#endif
