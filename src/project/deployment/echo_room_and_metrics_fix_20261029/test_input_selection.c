#include "../echo_interface_guard_20261026/gateway/src/feature_runtime.c"
#include <assert.h>
static uint32_t fp(float f){uint32_t w;memcpy(&w,&f,4);return w;}
int main(void){static gw g;static fx_manager m;uint32_t chosen=99;g.now_ms=1000;m.quality_poll=1000;m.quality_received=1000;m.quality_count=8;
 for(unsigned k=0;k<8;k++)for(unsigned ch=0;ch<6;ch++){uint32_t*v=m.quality[k]+ch*8;v[0]=fp(ch==2?.001f:.01f);v[1]=fp(ch==2?.002f:.5f);v[7]=1;}
 for(unsigned k=0;k<8;k++){m.quality[k][4*8]=0;m.quality[k][4*8+1]=0;m.quality[k][4*8+7]=0;m.quality[k][3*8+6]=1;}
 assert(select_input(&g,&m,&chosen)==0&&chosen==2);
 for(unsigned k=0;k<8;k++)for(unsigned ch=0;ch<6;ch++)m.quality[k][ch*8+7]=0;
 assert(select_input(&g,&m,&chosen)!=0);m.quality_count=2;assert(select_input(&g,&m,&chosen)!=0);
 puts("INPUT_SELECTION_TEST_PASS");return 0;}
