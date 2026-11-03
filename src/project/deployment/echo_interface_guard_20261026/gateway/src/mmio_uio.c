#include "mmio.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int gw_mmio_read_reg(const gw_mmio *m, uint32_t offset, uint32_t *value)
{
    if (!m || !value || !m->dev.read) return -1;
    return m->dev.read(m->dev.ctx, offset, value) ? -1 : 0;
}

#if defined(_WIN32)

int gw_mmio_open_uio(const char *uio_path, uint32_t mmio_bytes,
                     gw_mmio **out, char *err, size_t errcap)
{
    (void)uio_path;
    (void)mmio_bytes;
    (void)out;
    if (err && errcap) snprintf(err, errcap,
        "UIO backend is POSIX/Linux only; host build must use --mock-fixture");
    return -1;
}

int gw_mmio_open_memdev(const char *memdev_path, uint32_t phys_base,
                        uint32_t mmio_bytes, gw_mmio **out,
                        char *err, size_t errcap)
{
    (void)memdev_path;
    (void)phys_base;
    (void)mmio_bytes;
    (void)out;
    if (err && errcap) snprintf(err, errcap,
        "/dev/mem backend is POSIX/Linux only; host build must use --mock-fixture");
    return -1;
}

int gw_mmio_map_ddr(gw_mmio *m, const char *memdev_path, uint32_t phys_base,
                    uint32_t bytes, char *err, size_t errcap)
{
    (void)m;
    (void)memdev_path;
    (void)phys_base;
    (void)bytes;
    if (err && errcap) snprintf(err, errcap, "DDR mapping is POSIX/Linux only");
    return -1;
}

void gw_mmio_close(gw_mmio *m)
{
    if (!m) return;
    if (m->destroy) m->destroy(m);
}

#else /* POSIX */

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct {
    int reg_fd;
    void *regs;
    size_t reg_bytes;
    uint32_t reg_page_offset;
    int mem_fd;
    void *ddr;
    size_t ddr_map_bytes;
    uint32_t ddr_phys_base;
    uint32_t ddr_bytes;
    uint32_t ddr_page_offset;
} uio_ctx;

/* This release requires O_SYNC mappings of the matching no-map reserved DDR.
 * An instruction-cache flush is not a data-cache coherency operation. Refuse an
 * unreserved mapping below rather than pretending it can be repaired here. */
static void arm_cache_flush(void *addr,size_t bytes){(void)addr;(void)bytes;__sync_synchronize();}

static void uio_barrier(void *ctx)
{
    (void)ctx;
    __sync_synchronize();
}

static int uio_read32(void *ctx, uint32_t offset, uint32_t *value)
{
    uio_ctx *c = (uio_ctx *)ctx;
    if (!c || !c->regs || !value || (offset & 3u) || offset + 4u > c->reg_bytes)
        return 1;
    __sync_synchronize();
    *value = *(volatile uint32_t *)((uint8_t *)c->regs + offset);
    __sync_synchronize();
    return 0;
}

static int uio_write32(void *ctx, uint32_t offset, uint32_t value)
{
    uio_ctx *c = (uio_ctx *)ctx;
    if (!c || !c->regs || (offset & 3u) || offset + 4u > c->reg_bytes)
        return 1;
    *(volatile uint32_t *)((uint8_t *)c->regs + offset) = value;
    __sync_synchronize();
    return 0;
}

static int ddr_range(const uio_ctx *c, uint32_t addr, uint32_t words, size_t *off)
{
    uint64_t begin, end, lo, hi;
    if (!c || !c->ddr) return -1;
    begin = (uint64_t)addr;
    end = begin + (uint64_t)words * 4u;
    lo = (uint64_t)c->ddr_phys_base;
    hi = lo + (uint64_t)c->ddr_bytes;
    if ((addr & 3u) || begin < lo || end > hi) return -1;
    *off = (size_t)(begin - lo);
    return 0;
}

static int ddr_read(void *ctx, uint32_t addr, uint32_t *dst, uint32_t words)
{
    uio_ctx *c = (uio_ctx *)ctx;
    size_t off = 0;
    if (!dst) return 1;
    if (ddr_range(c, addr, words, &off)) return 1;
    arm_cache_flush((uint8_t *)c->ddr + off, (size_t)words * 4u);
    __sync_synchronize();
    memcpy(dst, (uint8_t *)c->ddr + off, (size_t)words * 4u);
    __sync_synchronize();
    return 0;
}

static int ddr_invalidate(void *ctx, uint32_t addr, uint32_t bytes)
{
    uio_ctx *c = (uio_ctx *)ctx;
    size_t off = 0;
    if (!bytes || (bytes & 3u)) return 1;
    if (ddr_range(c, addr, bytes / 4u, &off)) return 1;
    arm_cache_flush((uint8_t *)c->ddr + off, bytes);
    __sync_synchronize();
    return 0;
}

static void uio_destroy(gw_mmio *m)
{
    uio_ctx *c = (uio_ctx *)m->state;
    if (!c) return;
    if (c->ddr) munmap(c->ddr, c->ddr_map_bytes);
    if (c->regs) munmap(c->regs, c->reg_bytes);
    if (c->mem_fd >= 0) close(c->mem_fd);
    if (c->reg_fd >= 0) close(c->reg_fd);
    free(c);
    free(m);
}

static int ddr_write_private(void *ctx,uint32_t address,const uint32_t *words,uint32_t count){
    uio_ctx *c=ctx;size_t off;uint32_t i,index;
    if(address<0x10000000u||address%4||ddr_range(c,address,count,&off))return 1;
    index=(address-0x10000000u)/4;
    if(!((index>=524288u&&(uint64_t)index+count<=525312u)||(index>=528384u&&(uint64_t)index+count<=529408u)||(index>=532480u&&(uint64_t)index+count<=537600u)||(index>=540672u&&(uint64_t)index+count<=545792u)))return 1;
    for(i=0;i<count;i++)((volatile uint32_t*)((uint8_t*)c->ddr+off))[i]=words[i];
    __sync_synchronize();return 0;
}

static int ddr_write_feature(void *ctx,uint32_t address,const uint32_t *words,uint32_t count){
    uio_ctx*c=ctx;size_t off;uint32_t index,i;
    if(address<0x10000000u||address%4||ddr_range(c,address,count,&off))return 1;
    index=(address-0x10000000u)/4;
    if(!((index>=1048576u&&(uint64_t)index+count<=4194304u)||(index>=525312u&&(uint64_t)index+count<=525376u)))return 1;
    for(i=0;i<count;i++)((volatile uint32_t*)((uint8_t*)c->ddr+off))[i]=words[i];
    __sync_synchronize();return 0;
}

static gw_mmio *uio_alloc(void)
{
    gw_mmio *m = (gw_mmio *)calloc(1, sizeof *m);
    uio_ctx *c = (uio_ctx *)calloc(1, sizeof *c);
    if (!m || !c) { free(m); free(c); return NULL; }
    c->reg_fd = -1;
    c->mem_fd = -1;
    m->state = c;
    m->dev.ctx = c;
    m->dev.read = uio_read32;
    m->dev.write = uio_write32;
    m->dev.barrier = uio_barrier;
    m->mem.ctx = c;
    m->mem.read = ddr_read;
    m->write_private = ddr_write_private;
    m->write_feature = ddr_write_feature;
    m->mem.invalidate = ddr_invalidate;
    m->mem.barrier = uio_barrier;
    m->mem.reserved_low = 0;
    m->mem.reserved_high = 0;
    m->destroy = uio_destroy;
    return m;
}

static long page_size(void)
{
    long p = sysconf(_SC_PAGESIZE);
    return p > 0 ? p : 4096;
}

static int map_file(const char *path, uint32_t offset_hint, size_t bytes,
                    int *fd_out, void **addr_out, size_t *map_bytes_out,
                    uint32_t *page_off_out, char *err, size_t errcap)
{
    long ps = page_size();
    uint32_t page_off = (uint32_t)(offset_hint & (uint32_t)(ps - 1));
    uint32_t base = offset_hint - page_off;
    size_t map_bytes = bytes + page_off;
    int fd = open(path, O_RDWR | O_SYNC);
    void *addr;
    if (fd < 0) {
        if (err && errcap) snprintf(err, errcap, "open(%s) failed", path);
        return -1;
    }
    addr = mmap(NULL, map_bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, (off_t)base);
    if (addr == MAP_FAILED) {
        if (err && errcap) snprintf(err, errcap, "mmap(%s) failed", path);
        close(fd);
        return -1;
    }
    *fd_out = fd;
    *addr_out = addr;
    *map_bytes_out = map_bytes;
    *page_off_out = page_off;
    return 0;
}

int gw_mmio_open_uio(const char *uio_path, uint32_t mmio_bytes,
                     gw_mmio **out, char *err, size_t errcap)
{
    gw_mmio *m;
    uio_ctx *c;
    if (!uio_path || !out || mmio_bytes == 0) return -1;
    m = uio_alloc();
    if (!m) return -1;
    c = (uio_ctx *)m->state;
    if (map_file(uio_path, 0, mmio_bytes, &c->reg_fd, &c->regs,
                 &c->reg_bytes, &c->reg_page_offset, err, errcap)) {
        gw_mmio_close(m);
        return -1;
    }
    c->regs = (uint8_t *)c->regs + c->reg_page_offset;
    c->reg_bytes = mmio_bytes;
    m->ddr_phys_base = 0;
    m->ddr_bytes = 0;
    *out = m;
    return 0;
}

int gw_mmio_open_memdev(const char *memdev_path, uint32_t phys_base,
                        uint32_t mmio_bytes, gw_mmio **out,
                        char *err, size_t errcap)
{
    gw_mmio *m;
    uio_ctx *c;
    if (!memdev_path || !out || mmio_bytes == 0 || (phys_base & 0xFFFu)) return -1;
    m = uio_alloc();
    if (!m) return -1;
    c = (uio_ctx *)m->state;
    if (map_file(memdev_path, phys_base, mmio_bytes, &c->reg_fd, &c->regs,
                 &c->reg_bytes, &c->reg_page_offset, err, errcap)) {
        gw_mmio_close(m);
        return -1;
    }
    c->regs = (uint8_t *)c->regs + c->reg_page_offset;
    c->reg_bytes = mmio_bytes;
    *out = m;
    return 0;
}

int gw_mmio_map_ddr(gw_mmio *m, const char *memdev_path, uint32_t phys_base,
                    uint32_t bytes, char *err, size_t errcap)
{
    uio_ctx *c;
    if (!m || !memdev_path || bytes == 0 || (phys_base & 0xFFFu)) {
        if (err && errcap) snprintf(err, errcap, "invalid DDR mapping window");
        return -1;
    }
    {
        unsigned char reg[8];FILE *file=fopen("/proc/device-tree/reserved-memory/echo-analysis@10000000/reg","rb");
        int valid=file && fread(reg,1,8,file)==8 && !memcmp(reg,"\x10\x00\x00\x00\x04\x00\x00\x00",8);
        if(file)fclose(file);
        if(!valid || phys_base!=0x10000000u || bytes!=0x04000000u ||
           access("/proc/device-tree/reserved-memory/echo-analysis@10000000/no-map",F_OK)) {
            if(err&&errcap)snprintf(err,errcap,"matching no-map reserved DDR is required");
            return -1;
        }
    }
    c = (uio_ctx *)m->state;
    if (map_file(memdev_path, phys_base, bytes, &c->mem_fd, &c->ddr,
                 &c->ddr_map_bytes, &c->ddr_page_offset, err, errcap)) {
        return -1;
    }
    c->ddr = (uint8_t *)c->ddr + c->ddr_page_offset;
    c->ddr_phys_base = phys_base;
    c->ddr_bytes = bytes;
    m->ddr_phys_base = phys_base;
    m->ddr_bytes = bytes;
    /* sm_copy_service() enforces reserved bounds; mirror the configured DDR
     * window; the caller refines it from config words 4/5 after commit. */
    m->mem.reserved_low = phys_base;
    m->mem.reserved_high = phys_base + bytes;
    return 0;
}

void gw_mmio_close(gw_mmio *m)
{
    if (!m) return;
    if (m->destroy) m->destroy(m);
}

#endif /* _WIN32 */
