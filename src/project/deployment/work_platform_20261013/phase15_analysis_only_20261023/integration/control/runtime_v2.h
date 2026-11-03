#ifndef SIXMIC_RUNTIME_V2_H
#define SIXMIC_RUNTIME_V2_H
#include <stdint.h>
// A single PS owner serializes MMIO; PC calls that owner over the later network service.
// io callbacks must use uncached device MMIO. DDR payload access separately needs
// A9 cache maintenance and DMB; this API does not dereference DMA buffers.
typedef struct {void *user;uint32_t (*read)(void*,uint32_t);void (*write)(void*,uint32_t,uint32_t);void (*barrier)(void*);} sm_io;
static inline uint64_t sm_capabilities(sm_io *io){return (uint64_t)io->read(io->user,12)|((uint64_t)io->read(io->user,16)<<32);}
// 0=stable, 1=not yet available, 2=producer outran bounded retries.
static inline int sm_snapshot(sm_io *io,uint32_t words[32],uint32_t *epoch,unsigned attempts){
 while(attempts--){uint32_t before=io->read(io->user,24);if(!before)return 1;
 io->barrier(io->user);for(unsigned k=0;k<32;k++)words[k]=io->read(io->user,256+4*k);
 io->barrier(io->user);uint32_t after=io->read(io->user,24);
 if(before==after){*epoch=after;return 0;}}
 return 2;
}
// Nonblocking configuration request. PL completion/rejection is polled separately.
// Return1 if another request is pending. Does not automatically reset hardware.
static inline int sm_submit(sm_io *io,const uint32_t words[16]){
 if(io->read(io->user,32)&1)return 1;
 for(unsigned k=0;k<16;k++)io->write(io->user,64+4*k,words[k]);
 io->barrier(io->user);io->write(io->user,32,1);return 0;
}
#endif
