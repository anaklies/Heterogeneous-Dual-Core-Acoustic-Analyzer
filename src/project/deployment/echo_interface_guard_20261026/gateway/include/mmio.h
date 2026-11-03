#ifndef GW_MMIO_H
#define GW_MMIO_H
/* Device access backends. The gateway only ever touches the PL through the
 * frozen integration host API types (sm_device / sm_memory from the read-only
 * integration tree): sixmic_host.c / service_result.c are compiled in, not
 * forked. Real register access is /dev/uioN or /dev/mem mmap with ARM
 * barriers; fixture tests use mock_mmio.c. */
#include <stddef.h>
#include <stdint.h>

#include "sixmic_host.h"
#include "service_result.h"

typedef struct gw_mmio gw_mmio;

struct gw_mmio {
    sm_device dev;   /* read32/write32/barrier used by sixmic_host.c */
    sm_memory mem;   /* DDR word reads + cache maintenance used by service_result.c */
    int (*write_private)(void *ctx,uint32_t address,const uint32_t *words,uint32_t count);
    int (*write_feature)(void *ctx,uint32_t address,const uint32_t *words,uint32_t count);
    void *state;
    /* Optional device-side state machine tick (mock model applies a pending
     * config commit here). May be NULL for real MMIO. */
    int (*tick)(gw_mmio *m);
    void (*destroy)(gw_mmio *m);
    /* Informational; 0 when unknown. */
    uint32_t ddr_phys_base;
    uint32_t ddr_bytes;
};

/* Read-only register access through the same sm_device callback. The frozen
 * host API exposes no helper for status/active-version/fault registers, so the
 * gateway reads them only, directly through the documented sm_device layer. */
int gw_mmio_read_reg(const gw_mmio *m, uint32_t offset, uint32_t *value);

/* Real backends. Both return 0 and fill *out, or -1 with err text.
 * /dev/uioN: maps resource0 (offset 0) of the PL HOST window.
 * /dev/mem: maps phys_base..phys_base+bytes of the PL HOST window.
 * Neither is board-validated; see docs/INTERFACE_GAPS.md. */
int gw_mmio_open_uio(const char *uio_path, uint32_t mmio_bytes,
                     gw_mmio **out, char *err, size_t errcap);
int gw_mmio_open_memdev(const char *memdev_path, uint32_t phys_base,
                        uint32_t mmio_bytes, gw_mmio **out,
                        char *err, size_t errcap);
/* Maps reserved DDR so the sm_memory callbacks can copy clips and service
 * snapshots. Requires the address window to be reserved in the device tree. */
int gw_mmio_map_ddr(gw_mmio *m, const char *memdev_path, uint32_t phys_base,
                    uint32_t bytes, char *err, size_t errcap);

void gw_mmio_close(gw_mmio *m);

#endif
