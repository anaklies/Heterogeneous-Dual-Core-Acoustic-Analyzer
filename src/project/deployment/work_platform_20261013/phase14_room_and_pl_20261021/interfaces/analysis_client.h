#ifndef SIXMIC_ANALYSIS_CLIENT_H
#define SIXMIC_ANALYSIS_CLIENT_H
#include <stdint.h>
#include "function_registry.h"
typedef uint32_t (*sixmic_read32)(void *context,uint32_t offset);
typedef int (*sixmic_write32)(void *context,uint32_t offset,uint32_t value);
typedef struct {void *context;sixmic_read32 read;sixmic_write32 write;} sixmic_io;
// Native, ARM orPC transport adapter supplies actual accesses. NoDSP onPS.
int sixmic_read_result(sixmic_io io,uint32_t words[32],uint32_t *epoch);
int sixmic_submit(sixmic_io io,uint32_t request_id,uint64_t ps_p1,uint64_t pc_p1,
                  uint64_t ps_p2,uint64_t pc_p2,int pause_p1);
int sixmic_poll_configuration(sixmic_io io,uint32_t request_id,uint32_t *version);
#endif
