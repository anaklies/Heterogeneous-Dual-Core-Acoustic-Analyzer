#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <math.h>
#include "sixmic_host.h"
static int rd(void *p,uint32_t o,uint32_t*v){if(o>=4096||o%4)return -1;*v=((volatile uint32_t*)p)[o/4];return 0;}
static int wr(void*p,uint32_t o,uint32_t v){(void)p;(void)o;(void)v;return -1;}
static void barrier(void*p){(void)p;__sync_synchronize();}
int main(void){
 int fd=open("/dev/mem",O_RDONLY|O_SYNC);if(fd<0)return 1;
 void *regs=mmap(0,4096,PROT_READ,MAP_SHARED,fd,0x43c20000);
 volatile uint32_t *ddr=mmap(0,0x4000000,PROT_READ,MAP_SHARED,fd,0x10000000);
 if(regs==MAP_FAILED||(void*)ddr==MAP_FAILED)return 2;
 sm_device d={regs,rd,wr,barrier};sm_snapshot a,b;uint32_t data[6][8];int ok=0;
 double total[6],tone[6],low[6];float peakpower[6];unsigned peakbin[6];
 for(int tries=0;tries<8&&!ok;tries++){
  if(sm_read_snapshot(&d,&a,3))continue;
  uint32_t base=a.word[6];
  if(base<0x10000000||base>0x13fc0000)return 3;
  for(int c=0;c<6;c++)for(int k=0;k<8;k++)data[c][k]=ddr[(base-0x10000000)/4+c*8192+7171+k];
  for(int c=0;c<6;c++){
   total[c]=tone[c]=low[c]=0;peakpower[c]=0;peakbin[c]=0;
   for(unsigned k=0;k<=1024;k++){
    float v=sm_word_float(ddr[(base-0x10000000)/4+c*8192+4098+3*k]);
    if(!isfinite(v)||v<0)continue;
    total[c]+=v;if(k>=41&&k<=45)tone[c]+=v;if(k<9)low[c]+=v;
    if(v>peakpower[c]){peakpower[c]=v;peakbin[c]=k;}
   }
  }
  __sync_synchronize();if(sm_read_snapshot(&d,&b,3))continue;
  ok=a.word[2]==b.word[2]&&a.word[3]==b.word[3]&&a.word[6]==b.word[6];
 }
 if(!ok)return 4;
 printf("INPUT_STATS frame=%u config=%u faults=0x%08x mic=0x%08x dropped=%u\n",a.word[2],a.word[3],a.word[10],a.word[11],a.word[13]);
 for(int c=0;c<6;c++)printf("CH%d rms=%g peak=%g span=%g mean=%g dBFS=%g crest=%g clips=%g valid=%g\n",c+1,sm_word_float(data[c][0]),sm_word_float(data[c][1]),sm_word_float(data[c][2]),sm_word_float(data[c][3]),sm_word_float(data[c][4]),sm_word_float(data[c][5]),sm_word_float(data[c][6]),sm_word_float(data[c][7]));
 for(int c=0;c<6;c++)printf("FFT_CH%d peak_hz=%.2f tone1k_fraction=%.5f low200_fraction=%.5f totalPower=%.9g\n",c+1,peakbin[c]*sm_word_float(a.word[31])/2048.f,total[c]>0?tone[c]/total[c]:0,total[c]>0?low[c]/total[c]:0,total[c]);
 /* Read-only electrical diagnostic: recent planar input words. These are
  * not claimed to be a leased waveform or aligned with the FFT snapshot. */
 uint32_t slot=a.word[5];
 if(slot<4){uint32_t input=a.word[6]-0x100000-(slot<<18)+(slot<<16);
  if(input>=0x10000000&&input+49152<=0x14000000)
   for(int c=0;c<6;c++){printf("RECENT_PCM_CH%d",c+1);for(int i=0;i<16;i++)printf(" %08x",ddr[(input-0x10000000)/4+c*2048+i*31]);printf("\n");}
 }
 munmap(regs,4096);munmap((void*)ddr,0x4000000);close(fd);return 0;
}
