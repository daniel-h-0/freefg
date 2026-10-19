/* SPDX-License-Identifier: MIT
 * Release-time controller of the present pacer, driven with the ready-time patterns measured in CONTROL Resonant. */
#include "wave_layer.c"
#include <assert.h>
#include <math.h>
struct run {double sd,mean,max_hold,last_hold;};
/* Feeds ready times built from a repeating gap pattern (ms); release i happens at pace_target(ready i). */
static struct run simulate(const double*gaps,int ngaps,int frames,int warmup,int hitch_at,double hitch_ms){
 pace_rn=0;pace_prev=0;pace_margin=0;pace_margin_t=0;pace_sn=0;for(int i=0;i<8;i++)pace_hold[i]=0;
 double g=1000.0,prev=0,sum=0,sum2=0,max_hold=0,hold=0;int n=0;
 for(int i=0;i<frames;i++){
  g+=(i==hitch_at?hitch_ms:gaps[i%ngaps])*1e-3;
  double d=pace_target(g);pace_prev=d;hold=d-g;assert(hold>=0);
  if(i>warmup){double iv=(d-prev)*1e3;sum+=iv;sum2+=iv*iv;n++;if(hold>max_hold)max_hold=hold;}
  prev=d;
 }
 double mean=sum/n;return (struct run){sqrt(fmax(0,sum2/n-mean*mean)),mean,max_hold*1e3,hold*1e3};
}
/* CONTROL Resonant 3x: each game frame's three presents become ready 18.2/6.0/4.1 ms apart. Every `every`-th group
 * the game frame is `late_ms` late (its CPU work ran long) and the next gap is that much shorter. Returns the number of
 * release intervals over 1.2x the period after the first `warmup` frames. */
static int jitter_run(int every,double late_ms,int frames,int warmup,double*max_margin){
 pace_rn=0;pace_prev=0;pace_margin=0;pace_margin_t=0;pace_sn=0;for(int i=0;i<8;i++)pace_hold[i]=0;
 const double gaps[]={18.2,6.0,4.1};double g=1000.0,prev=0;int longs=0;*max_margin=0;
 for(int i=0;i<frames;i++){
  int grp=i/3,pos=i%3;double gap=gaps[pos];
  if(pos==0&&grp%every==every-1)gap+=late_ms; else if(pos==0&&grp%every==0&&grp)gap-=late_ms;
  g+=gap*1e-3;double d=pace_target(g);pace_prev=d;assert(d>=g);
  if(i>warmup&&(d-prev)*1e3>1.2*28.3/3)longs++;
  if(pace_margin>*max_margin)*max_margin=pace_margin;prev=d;
 }
 return longs;
}
int main(void){
 setvbuf(stdout,NULL,_IONBF,0);
 double mm;int longs=jitter_run(1000000,0,3000,96,&mm);
 printf("3x 18.2/6.0/4.1 steady: %d long intervals, margin %.2f ms\n",longs,mm*1e3);
 assert(longs==0&&mm==0); /* a stream that never misses gets no margin (no added latency) */
 longs=jitter_run(12,3.0,3000,96,&mm);
 printf("3x with a 3 ms late game frame every 12th group: %d long intervals over %d groups, max margin %.2f ms\n",longs,3000/3/12,mm*1e3);
 assert(longs<=2&&mm<=PACE_MARGIN_MAX+1e-9); /* the margin builds on the first misses, then later slips fit in it */
 const double two[]={15.5,20.0},three[]={6.0,4.5,30.1},steady[]={16.7};
 struct run r=simulate(two,2,400,64,-1,0);
 printf("2x 15.5/20: interval %.2f sd %.3f max hold %.2f ms\n",r.mean,r.sd,r.max_hold);
 assert(fabs(r.mean-17.75)<0.05&&r.sd<0.3&&r.max_hold<2.6);
 r=simulate(three,3,600,96,-1,0);
 printf("3x 6/4.5/30.1: interval %.2f sd %.3f max hold %.2f ms\n",r.mean,r.sd,r.max_hold);
 assert(fabs(r.mean-13.53)<0.05&&r.sd<0.7&&r.max_hold<3.5*13.53);
 r=simulate(steady,1,300,40,-1,0);
 printf("even 16.7: interval %.2f sd %.3f max hold %.2f ms\n",r.mean,r.sd,r.max_hold);
 assert(r.sd<0.01&&r.max_hold<0.01); // An already even stream is never held.
 r=simulate(two,2,400,64,200,45.0); // One late frame, then the pattern resumes; the backlog must drain.
 printf("2x with a 45 ms hitch: final hold %.2f ms\n",r.last_hold);
 assert(r.last_hold<2.6);
 r=simulate(two,2,300,40,150,250.0); // A pause longer than 100 ms restarts the estimate: the next frame goes out when ready.
 assert(r.last_hold<2.6);
 /* Who gets output pacing: BC250_XEFG_PACE decides; otherwise every game under gamescope. The X nudge (stock gamescope)
  * is on unless the patched gamescope's session variable is set; BC250_XEFG_PACE_NUDGE overrides. */
 unsetenv("BC250_XEFG_PACE");unsetenv("BC250_XEFG_PACE_NUDGE");unsetenv("BC250_GAMESCOPE_READY_NUDGE");unsetenv("GAMESCOPE_WAYLAND_DISPLAY");
 assert(!pace_wanted()&&pace_nudge_wanted());
 setenv("BC250_GAMESCOPE_READY_NUDGE","1",1);assert(!pace_wanted()&&!pace_nudge_wanted()); /* desktop session inheriting environment.d */
 setenv("GAMESCOPE_WAYLAND_DISPLAY","gamescope-0",1);assert(pace_wanted()&&!pace_nudge_wanted());  /* patched gamescope */
 unsetenv("BC250_GAMESCOPE_READY_NUDGE");assert(pace_wanted()&&pace_nudge_wanted());              /* stock gamescope */
 setenv("BC250_XEFG_PACE_NUDGE","0",1);assert(!pace_nudge_wanted());
 setenv("BC250_GAMESCOPE_READY_NUDGE","1",1);setenv("BC250_XEFG_PACE_NUDGE","1",1);assert(pace_nudge_wanted());
 setenv("BC250_XEFG_PACE","0",1);assert(!pace_wanted());
 unsetenv("GAMESCOPE_WAYLAND_DISPLAY");setenv("BC250_XEFG_PACE","1",1);assert(pace_wanted());
 setenv("BC250_XEFG_PACE","auto",1);setenv("GAMESCOPE_WAYLAND_DISPLAY","gamescope-0",1);assert(pace_wanted()&&!pace_forced());
 unsetenv("GAMESCOPE_WAYLAND_DISPLAY");assert(!pace_wanted());
 setenv("BC250_XEFG_PACE","1",1);assert(pace_forced());setenv("BC250_XEFG_PACE","0",1);assert(!pace_forced());unsetenv("BC250_XEFG_PACE");assert(!pace_forced());
 /* Intel's shaders (BC250_XEFG_DISABLE, another GPU): since v30 the add-on counts generation from the SDK's present
  * status there too, so they follow the signal instead of holding every present. */
 setenv("BC250_XEFG_DISABLE","1",1);assert(!pace_forced());
 setenv("BC250_XEFG_PACE","auto",1);assert(!pace_forced());setenv("BC250_XEFG_PACE","1",1);assert(pace_forced());
 unsetenv("BC250_XEFG_PACE");unsetenv("BC250_XEFG_DISABLE");
 puts("pace_wanted: every game under gamescope; X nudge unless the patched gamescope's variable; overrides; auto");
 /* XeFG signal: hold only while the add-on's count moves (250 ms window). No page, or an add-on that has not answered
  * 3 s after the page was made: hold every present (v23 behaviour). */
 static struct pace_signal_page page;pace_force=0;
 assert(pace_holding(1.0));                                  /* no page */
 pace_sig=&page;pace_sig_made=1.0;assert(!pace_holding(1.5)); /* page, add-on not heard yet, within 3 s */
 assert(pace_holding(4.5));                                  /* add-on silent for 3.5 s */
 page.beat=1;assert(!pace_holding(4.6));                     /* add-on alive, nothing generated */
 page.generated=7;page.beat=2;assert(pace_holding(5.0));assert(pace_holding(5.2));
 assert(!pace_holding(5.3));                                 /* stopped for 300 ms */
 page.generated=9;assert(pace_holding(6.0));
 pace_force=1;assert(pace_holding(9.0));                    /* BC250_XEFG_PACE=1 */
 /* A page left by an earlier process with this Windows pid, already mapped by the add-on: the layer keeps that file. */
 char stale[64];snprintf(stale,sizeof(stale),"/dev/shm/bc250-xefg-pace-test-%d",(int)getpid());
 int sfd=open(stale,O_RDWR|O_CREAT|O_TRUNC,0600);assert(sfd>=0&&ftruncate(sfd,4096)==0);
 struct pace_signal_page*addon=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,sfd,0);assert(addon!=MAP_FAILED);close(sfd);
 memcpy(addon->magic,"BC250XP1",8);addon->owner=999999;addon->generated=77;addon->beat=5;
 pace_sig=NULL;pace_signal_sweep(stale);assert(access(stale,F_OK)==0);
 assert(pace_signal_map(stale)&&pace_sig->beat==0&&pace_sig->generated==0&&pace_sig->owner==(uint32_t)getpid());
 addon->beat++;addon->generated++;assert(pace_sig->beat==1&&pace_sig->generated==1); /* the add-on's writes reach the layer */
 munmap(addon,4096);munmap(pace_sig,4096);unlink(stale);
 pace_sig=NULL;pace_force=-1;
 puts("pace_holding: only while XeFG generates; forced, no page or silent add-on hold every present");
 puts("PASS present pacer: 2x and 3x patterns even, steady stream untouched, hitch backlog drains, pause resets, gate, stale signal page");return 0;
}
