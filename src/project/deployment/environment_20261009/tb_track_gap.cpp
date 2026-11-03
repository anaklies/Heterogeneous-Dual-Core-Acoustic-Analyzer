#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
extern void track_sources(const int32_t *, float, bool, int32_t *);
int main(int argc, char **argv) {
    const char *path =
        argc == 2 ? argv[1] : "C:/Users/sunxi/Desktop/sixmic3D/deployment/environment_20261009/gap_golden.bin";
    FILE *f = fopen(path, "rb");
    if (!f)
        return 2;
    int32_t in[52], gold[52], out[52], reset;
    float dt;
    int frames = 0, errors = 0, maxdelta = 0;
    while (fread(in, 4, 52, f) == 52) {
        if (fread(gold, 4, 52, f) != 52 || fread(&dt, 4, 1, f) != 1 || fread(&reset, 4, 1, f) != 1)
            return 3;
        track_sources(in, dt, reset != 0, out);
        frames++;
        if (out[0] != gold[0]) {
            errors++;
            printf("count mismatch %d %d %d\n", frames, out[0], gold[0]);
            continue;
        }
        for (int i = 0; i < gold[0]; i++) {
            int b = 7 + 15 * i, found = -1;
            for (int j = 0; j < out[0]; j++)
                if (out[7 + 15 * j] == gold[b])
                    found = j;
            if (found < 0) {
                errors++;
                continue;
            }
            int a = 7 + 15 * found;
            for (int k = 1; k < 15; k++) {
                int delta = abs(out[a + k] - gold[b + k]);
                bool exact = k == 1 || k >= 11;
                if (!exact && delta > maxdelta)
                    maxdelta = delta;
                if ((exact && delta != 0) || (!exact && delta > 16)) {
                    if (errors < 6)
                        printf("mismatch frame=%d ID=%d word=%d delta=%d\n", frames, gold[b], k,
                               delta);
                    errors++;
                }
            }
        }
    }
    fclose(f);
    printf("MATLAB tracker comparison: frames=%d errors=%d maxCoordinateOrDirectionQ16Delta=%d\n",
           frames, errors, maxdelta);
    return errors ? 1 : 0;
}

