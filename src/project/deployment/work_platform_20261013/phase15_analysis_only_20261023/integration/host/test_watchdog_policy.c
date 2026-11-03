#include "watchdog_policy.h"
#include <assert.h>
#include <stdio.h>
int main(void){sm_watch_policy p={0};assert(sm_watch_step(&p,0,0,0,0,0,2000)==0);assert(sm_watch_step(&p,10,1,1,0,0,2000)==0);assert(sm_watch_step(&p,1000,1,1,0,0,2000)==0);assert(sm_watch_step(&p,1010,1,1,1,0,2000)==1);
assert(sm_watch_step(&p,1100,1,1,2,0xfff80400u,2000)==1);assert(sm_watch_step(&p,3000,0,0,0,0,2000)==1);assert(sm_watch_step(&p,3100,0,0,0,0,2000)==2);assert(p.reason==0x80000000u);
sm_watch_policy q={0};sm_watch_step(&q,0,1,1,1,0,2000);assert(sm_watch_step(&q,50,1,1,2,0x20,2000)==2);assert(q.reason==0x20);puts("WATCHDOG_POLICY_PASS real-progress arm sensor/quiet-warning immunity stalled/fatal paths");return 0;}
