#include "srpdnn_float.h"
#include <cstdio>

static float input[NN_PAIRS * NN_PAIR_INPUT];
static float phase[NN_PAIRS * NN_PAIR_PHASE];
static float support[NN_PAIRS * NN_PAIR_SUPPORT];
static float activity[27], count[4];

int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    FILE *f = std::fopen(argv[1], "rb");
    if (!f) return 3;
    const size_t n = std::fread(input, sizeof(float), NN_PAIRS * NN_PAIR_INPUT, f);
    const int extra = std::fgetc(f);
    std::fclose(f);
    if (n != NN_PAIRS * NN_PAIR_INPUT || extra != EOF) return 4;
    srpdnn_forward_float(input, phase, support, activity, count);
    f = std::fopen(argv[2], "wb");
    if (!f) return 5;
    const bool ok = std::fwrite(phase, sizeof(float), NN_PAIRS * NN_PAIR_PHASE, f) == NN_PAIRS * NN_PAIR_PHASE
        && std::fwrite(support, sizeof(float), NN_PAIRS * NN_PAIR_SUPPORT, f) == NN_PAIRS * NN_PAIR_SUPPORT
        && std::fwrite(activity, sizeof(float), 27, f) == 27
        && std::fwrite(count, sizeof(float), 4, f) == 4;
    return std::fclose(f) || !ok ? 6 : 0;
}
