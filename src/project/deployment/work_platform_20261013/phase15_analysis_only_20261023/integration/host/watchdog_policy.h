#ifndef SIXMIC_WATCHDOG_POLICY_H
#define SIXMIC_WATCHDOG_POLICY_H
#include <stdint.h>
typedef struct {uint64_t last_ms;uint32_t session,frame,reason;unsigned seen,armed,fatal;} sm_watch_policy;
/* Pure policy; never performs reboot, IO, signal processing or signal classification. */
static inline unsigned sm_watch_step(sm_watch_policy *p,uint64_t now,unsigned have,uint32_t session,uint32_t frame,uint32_t faults,uint32_t stall_ms) {
 if(p->fatal)return 2;
 if(have) {
  if(!p->seen){p->seen=1;p->session=session;p->frame=frame;p->last_ms=now;}
  else if(p->session!=session||p->frame!=frame){p->session=session;p->frame=frame;p->last_ms=now;p->armed=1;}
 }
 if(p->armed) {
  /* Numeric optional-service, sensor, quiet/constant mic and lost-event warnings
   * do not cause reboot loops. Transport/scheduler/feature faults are fatal. */
  if(have&&(faults&0x3feu)){p->fatal=1;p->reason=faults&0x3feu;return 2;}
  if(now>=p->last_ms&&now-p->last_ms>=stall_ms){p->fatal=1;p->reason=0x80000000u;return 2;}
  return 1;
 }
 return 0;
}
#endif
