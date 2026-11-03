#define _POSIX_C_SOURCE 200809L
#include "sixmic_host.h"
#include "watchdog_policy.h"
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <linux/watchdog.h>
#include <time.h>
#include <signal.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
/* Optional Linux management daemon. Do not install/enable on the host PC.
 * UIO mapping and a hardware PS watchdog must exist in the matching BSP. */
static volatile sig_atomic_t stop;
static void stopping(int n){(void)n;stop=1;}
static int read32(void *ctx,uint32_t off,uint32_t *v){*v=((volatile uint32_t*)ctx)[off/4];return 0;}
static int write32(void *ctx,uint32_t off,uint32_t v){(void)ctx;(void)off;(void)v;return -1;}
static void barrier(void *ctx){(void)ctx;__sync_synchronize();}
static uint64_t monotonic_ms(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;return (uint64_t)t.tv_sec*1000+t.tv_nsec/1000000;}
int main(int argc,char **argv){
 if(argc!=3){fprintf(stderr,"Usage: %s /dev/uioN /dev/watchdogN (board only)\n",argv[0]);return 2;}
 int uio=open(argv[1],O_RDWR|O_CLOEXEC);if(uio<0){perror("UIO");return 3;}
 void *map=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,uio,0);if(map==MAP_FAILED){perror("mmap");close(uio);return 3;}
 sm_device d={map,read32,write32,barrier};sm_identity id;
 if(sm_identify(&d,&id)!=SM_OK){fprintf(stderr,"Protocol3 device not found; watchdog not armed\n");munmap(map,4096);close(uio);return 4;}
 struct sigaction sa={0};sa.sa_handler=stopping;sigaction(SIGTERM,&sa,NULL);sigaction(SIGINT,&sa,NULL);
 sm_watch_policy p={0};int wdt=-1,rc=0;uint64_t began=monotonic_ms();
 while(!stop){
  sm_snapshot snap;int got=sm_read_snapshot(&d,&snap,3)==SM_OK;
  unsigned action=sm_watch_step(&p,monotonic_ms(),got,got?snap.word[4]:0,got?snap.word[2]:0,got?snap.word[10]:0,2000);
  if(action==1&&wdt<0){
   wdt=open(argv[2],O_WRONLY|O_CLOEXEC);if(wdt<0){perror("hardware watchdog unavailable");rc=6;break;}
   int timeout=10;if(ioctl(wdt,WDIOC_SETTIMEOUT,&timeout)<0){perror("watchdog timeout");rc=6;break;}
   fprintf(stderr,"Hardware watchdog armed after actual PL progress; timeout=%ds\n",timeout);fflush(stderr);
  }
  if(action==2){
   fprintf(stderr,"PL fatal/stalled reason=0x%08x: stop feeding hardware watchdog\n",p.reason);fflush(stderr);
   /* Keep the descriptor open. No local DMA-idle/AXI-reset acknowledgement is
    * fabricated. Hardware resets the whole matched PS/PL system after timeout. */
   while(!stop){struct timespec delay={0,100000000};nanosleep(&delay,NULL);}break;
  }
  if(wdt>=0&&ioctl(wdt,WDIOC_KEEPALIVE,0)<0){perror("watchdog feed");rc=6;break;}
  if(wdt<0&&monotonic_ms()-began>60000){fprintf(stderr,"No configured PL progress; watchdog remains unarmed\n");break;}
  struct timespec delay={0,50000000};nanosleep(&delay,NULL);
 }
 /* Explicit service stop is intentional; magic-close support is BSP-dependent. */
 if(wdt>=0){if(stop){ssize_t n=write(wdt,"V",1);(void)n;}close(wdt);}
 munmap(map,4096);close(uio);return p.fatal?5:rc;
}
