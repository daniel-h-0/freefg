/* SPDX-License-Identifier: MIT
 * Even presentation for frame generation under gamescope VRR.
 *
 * XeFG presents its generated and real frames back to back from one D3D12 queue while the game keeps submitting the
 * next frame to the same Vulkan graphics queue, so each frame becomes ready wherever the game's work happened to put
 * its blit: 15/20 ms at 2x, 8/13/19 ms at 3x. VRR shows exactly that. The pacer instead:
 *  - queues each present with a zero-work graphics submit that signals when the frame is rendered (the watcher thread
 *    stamps that time in order),
 *  - releases it no sooner than 99% of the mean ready interval after the previous release (the late frame of an uneven
 *    pattern goes out when ready, earlier ones wait for their slot),
 *  - presents from a compute queue reserved for the layer where the driver has one, otherwise from the game's queue
 *    with the device's queue entry points behind one lock (a present without a blit is not ordered behind newer work
 *    in Mesa's WSI either way),
 *  - adds swapchain capacity for held frames, and hides present-wait so vkd3d releases DXGI frame-latency objects
 *    on GPU completion rather than on the display of a frame the pacer is holding.
 * Gamescope imports new commits after it has handled the finished ones in each loop, and a commit that is already
 * complete at import (every held frame) gets no wakeup of its own: it would wait for gamescope's next vblank-timer tick,
 * which snaps VRR presents to the refresh grid (stock gamescope 3.16.x and master as of 2026-09-27). So after each paced
 * present the layer changes a property on the root window of the game's X display seven times between 0.15 and 2.6 ms
 * later: each change is an X event that wakes gamescope's loop, and the first one after gamescope has imported the frame
 * shows it (see pace_nudge). Gamescope imported a held frame 0.21 ms after the present (0.42 ms at p99, at most 2.5 ms)
 * in Kingdom Come II; with the nudge it showed it 1.16 ms after the release (patched gamescope: 0.98 ms). Denser nudges
 * did not help (the X round trip itself sets the delay). A gamescope with the ready-commit fix (session variable
 * BC250_GAMESCOPE_READY_NUDGE=1) needs no nudge. The nudge costs seven X requests per frame, no GPU work, and about 0.7%
 * of one CPU core in gamescope. (A GPU-side gate that presented at once and waited on the layer's queue did the same without X, but its wait cost
 * games 8-20% frame rate.)
 * Frames are held only while XeFG generates them (the BC250 add-on's signal, pace_holding): the uneven ready times come
 * from XeFG's real-frame copy, while FSR 3 FG paces its own presents (holding on top of it cost Cyberpunk 1.5%) and
 * frames without generation need no slot. Those go out as soon as they are rendered, still through the reserved queue
 * and with the nudge. Until the add-on has answered once (pace_engaged), presents and acquires go straight to the
 * driver: a launcher, a game before its XeFG context or a process without the add-on gets no extra submit, wait, thread
 * wakeup or X traffic. BC250_XEFG_PACE=1 holds every present from the first. Only Wine game threads under gamescope
 * are paced at all (pace_wanted). */
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#define PACE_SLOTS 16
struct pace_job {VkQueue queue;VkSwapchainKHR chain;uint32_t index;unsigned slot;double arrive,ready;
 int has_fence;VkFence present_fence;int has_mode;VkPresentModeKHR mode;int has_id;uint64_t id;int has_id2;uint64_t id2;
};
static struct {pthread_mutex_t lock;pthread_cond_t cv;struct pace_job jobs[PACE_SLOTS];unsigned head,tail,watch;int threads,ring;
 struct device_state*d;VkFence fences[PACE_SLOTS];VkSemaphore sems[PACE_SLOTS];VkResult error;VkSwapchainKHR error_chain;} pq={.lock=PTHREAD_MUTEX_INITIALIZER,.cv=PTHREAD_COND_INITIALIZER};
static pthread_mutex_t chain_lock=PTHREAD_MUTEX_INITIALIZER; /* acquire and the releaser's present share each swapchain */
/* Without a dedicated compute queue (stock Mesa disables it on the BC-250) the releaser presents from the application's own
 * queue. Mesa's WSI presents without a blit by copying semaphore payloads on the CPU (wsi_queue_submit2_unordered), so the
 * held present is not ordered behind newer work on that queue; the layer only has to make its calls on the queue
 * externally synchronized with the application's, which this lock does (taken around every queue call of such a device). */
static pthread_mutex_t shared_queue_lock=PTHREAD_MUTEX_INITIALIZER;
static int pace_on(const struct device_state*d){return d->pace_queue!=VK_NULL_HANDLE||d->pace_shared;}
static void queue_lock(const struct device_state*d){if(d->pace_shared)pthread_mutex_lock(&shared_queue_lock);}
static void queue_unlock(const struct device_state*d){if(d->pace_shared)pthread_mutex_unlock(&shared_queue_lock);}
/* BC250_XEFG_PACE_QUEUE=app presents from the application's queue even when a compute queue exists (for comparisons). */
static int pace_app_queue(void){const char*v=getenv("BC250_XEFG_PACE_QUEUE");return v&&!strcmp(v,"app");}
static VkResult pace_submit(struct device_state*d,VkQueue queue,const VkSubmitInfo*submit,VkFence fence){
 queue_lock(d);VkResult r=d->submit(queue,1,submit,fence);queue_unlock(d);return r;
}
static FILE*pace_log;static pthread_mutex_t pace_log_lock=PTHREAD_MUTEX_INITIALIZER;
static double pace_rt[64],pace_hold[8],pace_prev;static unsigned pace_rn;static int pace_nudge_on;

/* BC250_XEFG_PACE=0/1 decides; otherwise (unset or "auto") every game that runs under gamescope (which exports
 * GAMESCOPE_WAYLAND_DISPLAY to its clients) goes through the pacer, with stock or patched gamescope. */
/* -1 unset/auto (or unknown, with a warning), 0 off/0/false/no, 1 on/1/true/yes. */
static int pace_switch(const char*name){
 const char*v=getenv(name);if(!v||!*v||!strcasecmp(v,"auto"))return -1;
 if(!strcmp(v,"0")||!strcasecmp(v,"off")||!strcasecmp(v,"false")||!strcasecmp(v,"no"))return 0;
 if(!strcmp(v,"1")||!strcasecmp(v,"on")||!strcasecmp(v,"true")||!strcasecmp(v,"yes"))return 1;
 fprintf(stderr,"BC250_PACE: %s=%s not understood (0/1, off/on); using auto\n",name,v);return -1;
}
static unsigned long pace_wine_pid(void);
/* A Wine game's thread: a prefix, and a Wine TEB in GS (pace_wine_pid). Native programs that inherit the game's
 * environment (a nested gamescope, a native launcher or tool) are never paced. */
static int pace_in_wine(void){return getenv("WINEPREFIX")!=NULL&&pace_wine_pid()!=0;}
static int pace_wanted(void){int v=pace_switch("BC250_XEFG_PACE");if(v>=0)return v;return getenv("GAMESCOPE_WAYLAND_DISPLAY")!=NULL&&pace_in_wine();}
static const char*pace_off_reason(void){
 return pace_switch("BC250_XEFG_PACE")==0?"BC250_XEFG_PACE=0":!getenv("GAMESCOPE_WAYLAND_DISPLAY")?"not under gamescope":
  "not a Wine game thread (no WINEPREFIX or no Wine TEB): native programs are not paced";
}
/* BC250_XEFG_PACE=1 holds every present for its slot; otherwise presents are held only while XeFG generates frames
 * (the add-on's signal below): FSR 3 FG, frame generation off and menus go out as soon as they are rendered. The signal
 * also counts with Intel's original shaders (BC250_XEFG_DISABLE, another GPU): the add-on reads the SDK's present status
 * there (until v29 those held every present, as v23). */
static int pace_forced(void){int forced=pace_switch("BC250_XEFG_PACE");return forced>0;}
/* XeFG generation signal. The BC250 add-on (a Windows DLL in the same Wine process) cannot call into this library, so
 * the layer creates a page in /dev/shm named after two things both sides can see: the Windows process id (the TEB's
 * ClientId, read on the Wine thread that presents; the add-on's GetCurrentProcessId) and the inode of the prefix's
 * drive_c (the add-on's C:\). /proc/self is no help there: Wine opens files in its server process. The add-on
 * (mfg_pace_signal.h) maps the page through Z: and stores the running count of generated frames (its accelerated
 * passes and the SDK's present status) every 20 ms. Frames are held while that count moved within the last 250 ms. Without a page, or while the add-on has
 * not answered (its heartbeat), presents pass straight through. Pages whose unix owner has exited are removed
 * when a new one is made, except this process's own name: Wine gives a game the same Windows pid on every launch, so after
 * an unclean exit the add-on may already have mapped the old page (it opens the page once); the layer reuses that file
 * and clears it rather than replacing it with a new one the add-on would never see. */
static double pace_now(void);
struct pace_signal_page {char magic[8];volatile uint64_t generated,beat;uint32_t owner;volatile uint32_t multiplier;};
_Static_assert(sizeof(struct pace_signal_page)==32,"XP1 pacing signal layout");
static struct pace_signal_page*pace_sig;static char pace_sig_path[96];static double pace_sig_made;
static uint64_t pace_sig_last,pace_sig_beat;static double pace_sig_when=-1e9;static int pace_sig_seen,pace_sig_heard,pace_sig_state=-1,pace_force=-1;
static void pace_signal_unlink(void){if(pace_sig_path[0])unlink(pace_sig_path);}
/* /dev/shm is shared by every user: a page is opened without following a symbolic link or blocking on a FIFO, and used
 * only when it is a regular file of this user. */
static int pace_signal_open(const char*path,int flags){
 int fd=open(path,flags|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);struct stat st;if(fd<0)return -1;
 if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid!=getuid()){close(fd);return -1;}
 return fd;
}
static unsigned long pace_wine_pid(void){
 unsigned long base=0;
 if(syscall(SYS_arch_prctl,0x1004 /* ARCH_GET_GS */,&base)||!base)return 0;
 if(*(unsigned long*)(base+0x30)!=base)return 0;      /* NT_TIB.Self: this is a Wine thread's TEB */
 return *(unsigned long*)(base+0x40);                  /* ClientId.UniqueProcess */
}
static void pace_signal_sweep(const char*keep){
 DIR*dir=opendir("/dev/shm");if(!dir)return;struct dirent*e;char path[300];
 while((e=readdir(dir))){if(strncmp(e->d_name,"bc250-xefg-pace-",16))continue;snprintf(path,sizeof(path),"/dev/shm/%s",e->d_name);if(!strcmp(path,keep))continue;
  int fd=pace_signal_open(path,O_RDONLY);if(fd<0)continue;struct pace_signal_page page;ssize_t n=read(fd,&page,sizeof(page));close(fd);
  if(n==(ssize_t)sizeof(page)&&page.owner&&page.owner!=(uint32_t)getpid()&&kill((pid_t)page.owner,0)&&errno==ESRCH)unlink(path);}
 closedir(dir);
}
/* Maps the page at path, reusing an existing file (see above), and clears it for this process. */
static int pace_signal_map(const char*path){
 int fd=pace_signal_open(path,O_RDWR|O_CREAT);if(fd<0)return 0;
 if(ftruncate(fd,4096)==0){void*m=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
  if(m!=MAP_FAILED){pace_sig=m;pace_sig->generated=0;pace_sig->beat=0;pace_sig->multiplier=0;pace_sig->owner=(uint32_t)getpid();memcpy(pace_sig->magic,"BC250XP1",8);pace_sig_made=pace_now();}}
 close(fd);return pace_sig!=NULL;
}
static void pace_signal_create(void){
 if(pace_sig)return;
 unsigned long wpid=pace_wine_pid();const char*prefix=getenv("WINEPREFIX");char drive[512];struct stat st;
 snprintf(drive,sizeof(drive),"%s/drive_c",prefix?prefix:"");
 if(!wpid||!prefix||stat(drive,&st)){fprintf(stderr,"BC250_PACE no XeFG signal (Windows pid %lu, prefix %s): presents pass through\n",wpid,prefix?"found":"missing");return;}
 snprintf(pace_sig_path,sizeof(pace_sig_path),"/dev/shm/bc250-xefg-pace-%llx-%lu",(unsigned long long)st.st_ino,wpid);
 pace_signal_sweep(pace_sig_path);
 if(pace_signal_map(pace_sig_path)){atexit(pace_signal_unlink);fprintf(stderr,"BC250_PACE XeFG signal page %s\n",pace_sig_path);}
 else{unlink(pace_sig_path);pace_sig_path[0]=0;}
}
static int pace_generating(double now){
 if(!pace_sig)return 0;
 uint64_t g=pace_sig->generated,b=pace_sig->beat;
 if(b!=pace_sig_beat){pace_sig_beat=b;pace_sig_heard=1;}
 if(g!=pace_sig_last){pace_sig_last=g;pace_sig_when=now;pace_sig_seen=1;}
 return pace_sig_seen&&now-pace_sig_when<0.25;
}
static int pace_holding(double now){
 if(pace_force<0)pace_force=pace_forced();
 int gen=pace_generating(now),state=pace_force?2:gen;
 if(state!=pace_sig_state){pace_sig_state=state;fprintf(stderr,"BC250_PACE %s\n",state==2?"holding every present (BC250_XEFG_PACE=1)":
  state?"holding: XeFG generates frames":"passing presents through: XeFG is not generating");}
 return pace_force||gen;
}
/* Whether presents go through the pacer: from the add-on's first heartbeat on (it never stops once on), or always with
 * BC250_XEFG_PACE=1. Before that, queue_present and the acquires call the driver directly. Called after pace_ready. */
static int pace_engaged;
static int pace_engage(void){
 if(__atomic_load_n(&pace_engaged,__ATOMIC_ACQUIRE))return 1;
 if(pace_force<=0&&!(pace_sig&&pace_sig->beat))return 0;  /* pace_force: set by pace_ready */
 if(!__atomic_exchange_n(&pace_engaged,1,__ATOMIC_ACQ_REL))
  fprintf(stderr,"BC250_PACE %s\n",pace_force>0?"pacing every present (BC250_XEFG_PACE=1)":"the BC250 add-on answered: presents go through the pacer");
 return 1;
}
/* Stock gamescope needs the X nudge; the patched build (its session variable) and BC250_XEFG_PACE_NUDGE=0 do without. */
static int pace_nudge_wanted(void){
 const char*v=getenv("BC250_XEFG_PACE_NUDGE");if(v)return strcmp(v,"0")!=0;
 v=getenv("BC250_GAMESCOPE_READY_NUDGE");return !(v&&!strcmp(v,"1"));
}
static double pace_now(void){struct timespec ts;clock_gettime(CLOCK_BOOTTIME,&ts);return ts.tv_sec+ts.tv_nsec*1e-9;}
static void pace_trace(char kind,double t0,double t1,int r,double extra){
 if(!pace_log)return;
 pthread_mutex_lock(&pace_log_lock);fprintf(pace_log,"%c %.6f %.3f %d %.3f\n",kind,t0,(t1-t0)*1e3,r,extra*1e3);fflush(pace_log);pthread_mutex_unlock(&pace_log_lock);
}
/* X nudge: a thread with its own connection to the game's X display (libX11 loaded at run time) changes a property on
 * the root window at the scheduled times. Each change reaches gamescope's X connection as a PropertyNotify and wakes its
 * loop; the property itself means nothing. */
#define NUDGE_SLOTS 64
typedef void*(*x_open_t)(const char*);typedef unsigned long(*x_atom_t)(void*,const char*,int);typedef unsigned long(*x_root_t)(void*);
typedef int(*x_change_t)(void*,unsigned long,unsigned long,unsigned long,int,int,const unsigned char*,int);typedef int(*x_flush_t)(void*);
static struct {pthread_mutex_t lock;pthread_cond_t cv;double due[NUDGE_SLOTS];unsigned head,tail;int state;void*dpy;unsigned long root,atom;
 x_change_t change;x_flush_t flush;uint32_t count;} nudge={.lock=PTHREAD_MUTEX_INITIALIZER,.cv=PTHREAD_COND_INITIALIZER};
static int nudge_open(void){
 const char*display=getenv("DISPLAY");void*x=display?dlopen("libX11.so.6",RTLD_NOW|RTLD_LOCAL):NULL;
 x_open_t open_display=x?(x_open_t)dlsym(x,"XOpenDisplay"):NULL;x_atom_t atom=x?(x_atom_t)dlsym(x,"XInternAtom"):NULL;
 x_root_t root=x?(x_root_t)dlsym(x,"XDefaultRootWindow"):NULL;nudge.change=x?(x_change_t)dlsym(x,"XChangeProperty"):NULL;nudge.flush=x?(x_flush_t)dlsym(x,"XFlush"):NULL;
 nudge.dpy=open_display&&atom&&root&&nudge.change&&nudge.flush?open_display(display):NULL;
 if(!nudge.dpy){fprintf(stderr,"BC250_PACE nudge unavailable (no X display); stock gamescope will show paced frames on its refresh grid\n");return 0;}
 nudge.root=root(nudge.dpy);nudge.atom=atom(nudge.dpy,"BC250_PACE_NUDGE",0);
 fprintf(stderr,"BC250_PACE nudge on %s\n",display);return 1;
}
static void*nudge_thread(void*unused){
 (void)unused;prctl(PR_SET_TIMERSLACK,1000UL,0,0,0); /* 1 us: the default 50 us slack would blur the nudge times */
 if(!nudge_open()){pthread_mutex_lock(&nudge.lock);nudge.state=-1;pthread_mutex_unlock(&nudge.lock);return NULL;}
 for(;;){
  pthread_mutex_lock(&nudge.lock);while(nudge.head==nudge.tail)pthread_cond_wait(&nudge.cv,&nudge.lock);
  double t=nudge.due[nudge.head%NUDGE_SLOTS];pthread_mutex_unlock(&nudge.lock);
  if(t>pace_now()){struct timespec ts={(time_t)t,0};ts.tv_nsec=(long)((t-(double)ts.tv_sec)*1e9);while(clock_nanosleep(CLOCK_BOOTTIME,TIMER_ABSTIME,&ts,NULL)==EINTR);}
  pthread_mutex_lock(&nudge.lock);nudge.head++;pthread_mutex_unlock(&nudge.lock);
  long value=++nudge.count; /* Xlib reads format-32 property data as long */
  nudge.change(nudge.dpy,nudge.root,nudge.atom,6/*XA_CARDINAL*/,32,0/*PropModeReplace*/,(const unsigned char*)&value,1);nudge.flush(nudge.dpy);
 }
 return NULL;
}
/* Schedules the nudges for a present made at r (called from the releaser). */
static void pace_nudge(double r){
 static const double after[]={0.00015,0.00025,0.00035,0.0005,0.0007,0.0010,0.0026};
 pthread_mutex_lock(&nudge.lock);
 if(!nudge.state){pthread_t t;nudge.state=pthread_create(&t,NULL,nudge_thread,NULL)==0?1:-1;if(nudge.state>0)pthread_detach(t);}
 if(nudge.state>0)for(unsigned i=0;i<sizeof(after)/sizeof(after[0]);i++){if(nudge.tail-nudge.head==NUDGE_SLOTS)nudge.head++;nudge.due[nudge.tail++%NUDGE_SLOTS]=r+after[i];}
 pthread_cond_signal(&nudge.cv);pthread_mutex_unlock(&nudge.lock);
}
/* Release time for a present that became ready at g. period: mean ready interval of the last 32 presents, measured
 * from GPU completion so holds cannot bias it. If every present of the last 8 (two MFG groups at 4x) was held beyond
 * the jitter margin, the queue carries a backlog from a hitch and drains at 95% of the period. Holds are capped at 3.5
 * periods (4.5 at 4x), because multi-frame generation can finish a whole group at once and needs room for its reserve.
 * Jitter margin: the earliest frame of each MFG group has no slack of its own, so a game frame that arrives a few ms
 * late (CONTROL Resonant's simulation step occasionally runs 21-28 instead of 15 ms) became one long refresh, which VRR
 * shows as flicker. Slots advance at 99% of the period (settling earlier) only while every recent frame had more slack
 * than pace_margin, otherwise at 100%. A miss (a frame ready after its slot, after a long interval, once the period rests on 32 frames) raises the margin
 * by 1 ms plus half the lateness. At 2x, misses under half a period count and the reserve is capped at 5 ms; at 3x/4x
 * those bounds scale with the number of generated frames (10/15 ms ceilings, from the SDK status signal); it decays
 * by 0.3 ms per second. A stream that never misses keeps no margin. Replay of 11 minutes of CONTROL Resonant 3x ready
 * times: 62% fewer long intervals for a 2.1 ms longer mean hold (CONTROL Resonant flicker study, 2026-09-29). */
#define PACE_MARGIN_MAX 0.005
#define PACE_MARGIN_DECAY 0.0003
/* A 4x batch has three generated frames competing with the next real frame's GPU work. The old 5 ms ceiling left
 * recurring misses even with steady simulation. Allow the existing adaptive reserve to grow per generated frame;
 * it still starts at zero and decays. 2x and an older producer keep exactly the original ceiling. */
static double pace_margin_limit(void){
 unsigned factor=pace_sig?pace_sig->multiplier:0;
 return factor==3?2*PACE_MARGIN_MAX:factor==4?3*PACE_MARGIN_MAX:PACE_MARGIN_MAX;
}
static double pace_margin,pace_margin_t,pace_slack[8];static unsigned pace_sn;
static double pace_target(double g){
 if(pace_rn&&(g-pace_rt[(pace_rn-1)%64]>0.1||g<pace_rt[(pace_rn-1)%64])){pace_rn=0;pace_prev=0;}
 if(!pace_rn)pace_sn=0;
 double margin_limit=pace_margin_limit();if(pace_margin>margin_limit)pace_margin=margin_limit;
 if(pace_margin_t>0){pace_margin-=PACE_MARGIN_DECAY*(g-pace_margin_t);if(pace_margin<0)pace_margin=0;}
 pace_margin_t=g;
 pace_rt[pace_rn%64]=g;pace_rn++;
 unsigned m=pace_rn<32?pace_rn:32;if(m<8||pace_prev<=0)return g;
 double period=(g-pace_rt[(pace_rn-m)%64])/(m-1);if(period<=0.002)return g;
 double lo=pace_hold[0];for(int i=1;i<8;i++)if(pace_hold[i]<lo)lo=pace_hold[i];
 double smin=1.0;if(pace_sn>=8){smin=pace_slack[0];for(int i=1;i<8;i++)if(pace_slack[i]<smin)smin=pace_slack[i];}
 double target=pace_prev+(lo>0.001+pace_margin?0.95:smin>pace_margin?0.99:1.0)*period;
 double hold_limit=pace_sig&&pace_sig->multiplier==4?4.5:3.5;
 if(target>g+hold_limit*period)target=g+hold_limit*period;
 double slack=target-g;pace_slack[pace_sn++%8]=slack;
 double miss_limit=0.5*period*(margin_limit/PACE_MARGIN_MAX);
 if(pace_rn>=32&&slack<0&&-slack<miss_limit&&g-pace_prev>1.12*period){pace_margin+=0.001+0.5*-slack;if(pace_margin>margin_limit)pace_margin=margin_limit;}
 if(target<g)target=g;
 pace_hold[pace_rn%8]=target-g;return target;
}
static void pace_drain(void){pthread_mutex_lock(&pq.lock);while(pq.head!=pq.tail)pthread_cond_wait(&pq.cv,&pq.lock);pthread_mutex_unlock(&pq.lock);}
static void*pace_watch(void*unused){
 (void)unused;
 for(;;){
  pthread_mutex_lock(&pq.lock);while(pq.watch==pq.tail)pthread_cond_wait(&pq.cv,&pq.lock);unsigned slot=pq.watch;struct device_state*d=pq.d;pthread_mutex_unlock(&pq.lock);
  for(int i=0;i<20&&d->wait_fences(d->device,1,&pq.fences[slot],VK_TRUE,100000000ull)==VK_TIMEOUT;i++);
  double t=pace_now();
  pthread_mutex_lock(&pq.lock);pq.jobs[slot].ready=t;pq.watch=(slot+1)%PACE_SLOTS;pthread_cond_broadcast(&pq.cv);pthread_mutex_unlock(&pq.lock);
 }
 return NULL;
}
static void*pace_release(void*unused){
 (void)unused;
 for(;;){
  pthread_mutex_lock(&pq.lock);while(pq.head==pq.tail||!pq.jobs[pq.head].ready)pthread_cond_wait(&pq.cv,&pq.lock);
  struct pace_job job=pq.jobs[pq.head];struct device_state*d=pq.d;pthread_mutex_unlock(&pq.lock);
  double start=pace_now(),target=job.ready;
  if(pace_holding(start))target=pace_target(job.ready);else{pace_rn=0;pace_prev=0;} /* the controller restarts when holding resumes */
  if(target>start){struct timespec ts={(time_t)target,0};ts.tv_nsec=(long)((target-(double)ts.tv_sec)*1e9);while(clock_nanosleep(CLOCK_BOOTTIME,TIMER_ABSTIME,&ts,NULL)==EINTR);}
  double r=pace_now();pace_prev=r;
  VkSwapchainPresentFenceInfoEXT fence_info={VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_EXT,NULL,1,&job.present_fence};
  VkSwapchainPresentModeInfoEXT mode_info={VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_MODE_INFO_EXT,NULL,1,&job.mode};
  VkPresentIdKHR id_info={VK_STRUCTURE_TYPE_PRESENT_ID_KHR,NULL,1,&job.id};
  VkPresentId2KHR id2_info={VK_STRUCTURE_TYPE_PRESENT_ID_2_KHR,NULL,1,&job.id2};
  const void*next=NULL;
  if(job.has_fence){fence_info.pNext=next;next=&fence_info;}
  if(job.has_mode){mode_info.pNext=next;next=&mode_info;}
  if(job.has_id){id_info.pNext=next;next=&id_info;}
  if(job.has_id2){id2_info.pNext=next;next=&id2_info;}
  VkResult result=VK_SUCCESS;VkPresentInfoKHR info={VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,next,1,&pq.sems[job.slot],1,&job.chain,&job.index,&result};
  VkQueue pq_queue=d->pace_queue?d->pace_queue:job.queue;
  pthread_mutex_lock(&chain_lock);queue_lock(d);VkResult rr=d->present(pq_queue,&info);queue_unlock(d);pthread_mutex_unlock(&chain_lock);
  double p1=pace_now();if(pace_nudge_on)pace_nudge(p1);pace_trace('P',r,p1,rr,0);
  if(rr==VK_SUCCESS)rr=result;
  pace_trace('Q',job.arrive,r,rr,job.ready-job.arrive);
  pthread_mutex_lock(&pq.lock);if(rr!=VK_SUCCESS&&(!pq.error||(rr<0&&pq.error>0))){pq.error=rr;pq.error_chain=job.chain;}
  pq.jobs[pq.head].ready=0;pq.head=(pq.head+1)%PACE_SLOTS;pthread_cond_broadcast(&pq.cv);pthread_mutex_unlock(&pq.lock);
 }
 return NULL;
}
/* One pacer per process, bound to the first device that presents through it; its fences and semaphores are recreated
 * if that device is destroyed. */
static int pace_ready(struct device_state*d){
 pthread_mutex_lock(&pq.lock);
 if(pq.ring){int ok=pq.ring>0&&pq.d==d;pthread_mutex_unlock(&pq.lock);return ok;}
 pq.ring=-1;int ok=1;
 for(int i=0;i<PACE_SLOTS&&ok;i++){VkFenceCreateInfo fi={VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,NULL,VK_FENCE_CREATE_SIGNALED_BIT};VkSemaphoreCreateInfo si={VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO,NULL,0};
  ok=d->create_fence(d->device,&fi,NULL,&pq.fences[i])==VK_SUCCESS&&d->create_sem(d->device,&si,NULL,&pq.sems[i])==VK_SUCCESS;}
 if(ok&&!pq.threads){pthread_t a,b;ok=pthread_create(&a,NULL,pace_watch,NULL)==0&&pthread_create(&b,NULL,pace_release,NULL)==0;if(ok){pthread_detach(a);pthread_detach(b);pq.threads=1;}}
 if(ok){pq.d=d;pq.ring=1;pq.head=pq.tail=pq.watch=0;pace_rn=0;pace_prev=0;pace_nudge_on=pace_nudge_wanted();
  pace_force=pace_forced();  /* here, under the lock: presenting threads read it in pace_engage */
  pace_signal_create();
  fprintf(stderr,"BC250_PACE hold%s%s\n",pace_forced()?"":" while XeFG generates, once the BC250 add-on answers",pace_nudge_on?" + X nudge (stock gamescope)":" (gamescope repaints for ready commits)");}
 const char*path=getenv("BC250_XEFG_PACE_TRACE");if(ok&&path&&!pace_log)pace_log=fopen(path,"a");
 pthread_mutex_unlock(&pq.lock);return ok;
}
static void pace_forget_device(struct device_state*d){
 pace_drain();pthread_mutex_lock(&pq.lock);
 if(pq.d==d){for(int i=0;i<PACE_SLOTS;i++){if(pq.fences[i])d->destroy_fence(d->device,pq.fences[i],NULL);if(pq.sems[i])d->destroy_sem(d->device,pq.sems[i],NULL);pq.fences[i]=VK_NULL_HANDLE;pq.sems[i]=VK_NULL_HANDLE;}pq.d=NULL;pq.ring=0;}
 pthread_mutex_unlock(&pq.lock);
}
/* A present takes its ring slot, submits into it and then publishes it; presents on two queues of one device may run
 * at the same time, so the whole sequence is one critical section. */
static pthread_mutex_t pace_enqueue=PTHREAD_MUTEX_INITIALIZER;
/* A stored deferred error belongs to its swapchain: it goes when that swapchain is destroyed or replaced. */
static void pace_forget_error(VkSwapchainKHR chain){
 if(!chain)return;
 pthread_mutex_lock(&pq.lock);if(pq.error&&pq.error_chain==chain)pq.error=VK_SUCCESS;pthread_mutex_unlock(&pq.lock);
}
static int pace_chain_ok(const void*next){
 for(const VkBaseInStructure*p=next;p;p=p->pNext)switch(p->sType){
  case VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_EXT:case VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_MODE_INFO_EXT:
  case VK_STRUCTURE_TYPE_PRESENT_ID_KHR:case VK_STRUCTURE_TYPE_PRESENT_ID_2_KHR:break;
  default:return 0;}
 return 1;
}
static struct device_state*device_by_key(void*key){
 struct device_state*r=NULL;pthread_mutex_lock(&mutex);for(struct device_state*p=devices;p;p=p->link)if(p->key==key){r=p;break;}pthread_mutex_unlock(&mutex);return r;
}
static VkResult VKAPI_CALL queue_present(VkQueue queue,const VkPresentInfoKHR*info){
 struct device_state*d=device_by_key(*(void**)queue);if(!d||!d->present)return VK_ERROR_INITIALIZATION_FAILED;
 double t0=pace_now();VkResult pending=VK_SUCCESS;
 pthread_mutex_lock(&pq.lock);if(pq.error&&info->swapchainCount==1&&pq.error_chain==info->pSwapchains[0]){pending=pq.error;pq.error=VK_SUCCESS;}pthread_mutex_unlock(&pq.lock);
 int pace=pace_on(d)&&pending==VK_SUCCESS&&info->swapchainCount==1&&info->waitSemaphoreCount<=8&&pace_chain_ok(info->pNext)&&pace_ready(d)&&pace_engage();
 if(pace){
  pthread_mutex_lock(&pace_enqueue);
  pthread_mutex_lock(&pq.lock);while((pq.tail+1)%PACE_SLOTS==pq.head)pthread_cond_wait(&pq.cv,&pq.lock);unsigned slot=pq.tail;pthread_mutex_unlock(&pq.lock);
  VkPipelineStageFlags stages[8];for(unsigned s=0;s<info->waitSemaphoreCount;s++)stages[s]=VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
  VkSubmitInfo submit={VK_STRUCTURE_TYPE_SUBMIT_INFO,NULL,info->waitSemaphoreCount,info->pWaitSemaphores,stages,0,NULL,1,&pq.sems[slot]};
  pace=d->wait_fences(d->device,1,&pq.fences[slot],VK_TRUE,1000000000ull)==VK_SUCCESS&&d->reset_fences(d->device,1,&pq.fences[slot])==VK_SUCCESS&&pace_submit(d,queue,&submit,pq.fences[slot])==VK_SUCCESS;
  if(!pace){pthread_mutex_lock(&pq.lock);pq.ring=-1;pthread_mutex_unlock(&pq.lock);pthread_mutex_unlock(&pace_enqueue);fprintf(stderr,"BC250_PACE disabled: present submit failed\n");}
  if(pace){
   struct pace_job job={.queue=queue,.chain=info->pSwapchains[0],.index=info->pImageIndices[0],.slot=slot,.arrive=t0};
   for(const VkBaseInStructure*p=info->pNext;p;p=p->pNext){
    if(p->sType==VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_EXT&&((const VkSwapchainPresentFenceInfoEXT*)p)->pFences){job.has_fence=1;job.present_fence=((const VkSwapchainPresentFenceInfoEXT*)p)->pFences[0];}
    if(p->sType==VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_MODE_INFO_EXT&&((const VkSwapchainPresentModeInfoEXT*)p)->pPresentModes){job.has_mode=1;job.mode=((const VkSwapchainPresentModeInfoEXT*)p)->pPresentModes[0];}
    if(p->sType==VK_STRUCTURE_TYPE_PRESENT_ID_KHR&&((const VkPresentIdKHR*)p)->pPresentIds){job.has_id=1;job.id=((const VkPresentIdKHR*)p)->pPresentIds[0];}
    if(p->sType==VK_STRUCTURE_TYPE_PRESENT_ID_2_KHR&&((const VkPresentId2KHR*)p)->pPresentIds){job.has_id2=1;job.id2=((const VkPresentId2KHR*)p)->pPresentIds[0];}
   }
   pthread_mutex_lock(&pq.lock);pq.jobs[slot]=job;pq.tail=(slot+1)%PACE_SLOTS;pthread_cond_broadcast(&pq.cv);pthread_mutex_unlock(&pq.lock);
   pthread_mutex_unlock(&pace_enqueue);
   if(info->pResults)info->pResults[0]=VK_SUCCESS;
   return VK_SUCCESS;
  }
 }
 pace_drain();pthread_mutex_lock(&chain_lock);queue_lock(d);VkResult r=d->present(queue,info);queue_unlock(d);pthread_mutex_unlock(&chain_lock);
 if(r==VK_SUCCESS&&pending!=VK_SUCCESS){if(info->pResults)info->pResults[0]=pending;return pending;}
 return r;
}
/* Acquire polls without blocking so it never holds the swapchain lock while waiting for an image. */
static VkResult pace_acquire_loop(VkResult(*try_once)(void*),void*ctx,uint64_t timeout){
 double a0=pace_now(),deadline=timeout>=(uint64_t)1e15?1e300:a0+timeout*1e-9;VkResult r;
 for(;;){pthread_mutex_lock(&chain_lock);r=try_once(ctx);pthread_mutex_unlock(&chain_lock);
  if((r!=VK_NOT_READY&&r!=VK_TIMEOUT)||pace_now()>=deadline)break;
  struct timespec ts={0,100000};nanosleep(&ts,NULL);}
 if(pace_log){double a1=pace_now();if(a1-a0>0.0002)pace_trace('A',a0,a1,r,0);}
 return r==VK_NOT_READY&&timeout?VK_TIMEOUT:r;
}
struct acquire_args {struct device_state*d;VkDevice device;VkSwapchainKHR chain;VkSemaphore sem;VkFence fence;uint32_t*index;const VkAcquireNextImageInfoKHR*info;};
static VkResult acquire_once(void*p){struct acquire_args*a=p;return a->d->acquire(a->device,a->chain,0,a->sem,a->fence,a->index);}
static VkResult acquire2_once(void*p){struct acquire_args*a=p;VkAcquireNextImageInfoKHR copy=*a->info;copy.timeout=0;return a->d->acquire2(a->device,&copy,a->index);}
static VkResult VKAPI_CALL acquire_image(VkDevice device,VkSwapchainKHR chain,uint64_t timeout,VkSemaphore sem,VkFence fence,uint32_t*index){
 struct device_state*d=device_by_key(*(void**)device);if(!d||!d->acquire)return VK_ERROR_INITIALIZATION_FAILED;
 /* Before the pacer is engaged no present runs on its threads, so the acquire needs neither the lock nor polling. */
 if(!pace_on(d)||!__atomic_load_n(&pace_engaged,__ATOMIC_ACQUIRE))return d->acquire(device,chain,timeout,sem,fence,index);
 struct acquire_args a={d,device,chain,sem,fence,index,NULL};return pace_acquire_loop(acquire_once,&a,timeout);
}
static VkResult VKAPI_CALL acquire_image2(VkDevice device,const VkAcquireNextImageInfoKHR*info,uint32_t*index){
 struct device_state*d=device_by_key(*(void**)device);if(!d||!d->acquire2)return VK_ERROR_INITIALIZATION_FAILED;
 if(!pace_on(d)||!__atomic_load_n(&pace_engaged,__ATOMIC_ACQUIRE))return d->acquire2(device,info,index);
 struct acquire_args a={d,device,VK_NULL_HANDLE,VK_NULL_HANDLE,VK_NULL_HANDLE,index,info};return pace_acquire_loop(acquire2_once,&a,info->timeout);
}
static VkResult VKAPI_CALL create_swapchain(VkDevice device,const VkSwapchainCreateInfoKHR*info,const VkAllocationCallbacks*a,VkSwapchainKHR*out){
 struct device_state*d=device_by_key(*(void**)device);if(!d||!d->create_swapchain)return VK_ERROR_INITIALIZATION_FAILED;
 pace_drain();pace_forget_error(info->oldSwapchain);VkSwapchainCreateInfoKHR copy=*info;
 if(pace_on(d)){
  /* A held 4x group can consume three images. With only one extra image, Acquire can stall new GPU work behind
   * our release times, making those holds feed back into the measured ready period after a hitch. */
  VkSurfaceCapabilitiesKHR caps;unsigned extra=1;uint32_t maximum=0;
  if(d->surface_caps&&d->surface_caps(d->physical,info->surface,&caps)==VK_SUCCESS){extra=3;maximum=caps.maxImageCount;}
  uint64_t desired=(uint64_t)copy.minImageCount+extra;
  if(maximum&&desired>maximum)desired=maximum;
  if(desired>UINT32_MAX)desired=UINT32_MAX;
  if(desired>copy.minImageCount)copy.minImageCount=(uint32_t)desired;
 }
 if(pace_on(d))fprintf(stderr,"BC250_PACE swapchain %ux%u images %u present mode %d\n",info->imageExtent.width,info->imageExtent.height,copy.minImageCount,(int)info->presentMode);
 return d->create_swapchain(device,&copy,a,out);
}
static void VKAPI_CALL destroy_swapchain(VkDevice device,VkSwapchainKHR chain,const VkAllocationCallbacks*a){
 struct device_state*d=device_by_key(*(void**)device);if(!d||!d->destroy_swapchain)return;pace_drain();pace_forget_error(chain);
 d->destroy_swapchain(device,chain,a);
}
static VkResult VKAPI_CALL queue_wait_idle(VkQueue queue){struct device_state*d=device_by_key(*(void**)queue);if(!d||!d->queue_wait_idle)return VK_ERROR_INITIALIZATION_FAILED;pace_drain();
 queue_lock(d);VkResult r=d->queue_wait_idle(queue);queue_unlock(d);return r;}
static VkResult VKAPI_CALL device_wait_idle(VkDevice device){struct device_state*d=device_by_key(*(void**)device);if(!d||!d->device_wait_idle)return VK_ERROR_INITIALIZATION_FAILED;pace_drain();
 queue_lock(d);VkResult r=d->device_wait_idle(device);queue_unlock(d);return r;}
/* Queue calls of a device whose presents share the application's queue (only returned for such devices, see gdpa). */
static VkResult VKAPI_CALL shared_submit(VkQueue q,uint32_t n,const VkSubmitInfo*s,VkFence f){struct device_state*d=device_by_key(*(void**)q);if(!d||!d->submit)return VK_ERROR_INITIALIZATION_FAILED;
 queue_lock(d);VkResult r=d->submit(q,n,s,f);queue_unlock(d);return r;}
static VkResult VKAPI_CALL shared_submit2(VkQueue q,uint32_t n,const VkSubmitInfo2*s,VkFence f){struct device_state*d=device_by_key(*(void**)q);if(!d||!d->submit2)return VK_ERROR_INITIALIZATION_FAILED;
 queue_lock(d);VkResult r=d->submit2(q,n,s,f);queue_unlock(d);return r;}
static VkResult VKAPI_CALL shared_submit2_khr(VkQueue q,uint32_t n,const VkSubmitInfo2*s,VkFence f){struct device_state*d=device_by_key(*(void**)q);if(!d||!d->submit2_khr)return VK_ERROR_INITIALIZATION_FAILED;
 queue_lock(d);VkResult r=d->submit2_khr(q,n,s,f);queue_unlock(d);return r;}
static void VKAPI_CALL shared_label_begin(VkQueue q,const VkDebugUtilsLabelEXT*l){struct device_state*d=device_by_key(*(void**)q);if(!d||!d->label_begin)return;queue_lock(d);d->label_begin(q,l);queue_unlock(d);}
static void VKAPI_CALL shared_label_end(VkQueue q){struct device_state*d=device_by_key(*(void**)q);if(!d||!d->label_end)return;queue_lock(d);d->label_end(q);queue_unlock(d);}
static void VKAPI_CALL shared_label_insert(VkQueue q,const VkDebugUtilsLabelEXT*l){struct device_state*d=device_by_key(*(void**)q);if(!d||!d->label_insert)return;queue_lock(d);d->label_insert(q,l);queue_unlock(d);}
static VkResult VKAPI_CALL shared_bind_sparse(VkQueue q,uint32_t n,const VkBindSparseInfo*b,VkFence f){struct device_state*d=device_by_key(*(void**)q);if(!d||!d->bind_sparse)return VK_ERROR_INITIALIZATION_FAILED;
 queue_lock(d);VkResult r=d->bind_sparse(q,n,b,f);queue_unlock(d);return r;}
/* The layer keeps the last queue of the compute-only family for its presents; the application sees one fewer. */
static void hide_pace_queue(VkQueueFamilyProperties*p){if(pace_wanted()&&!pace_app_queue()&&(p->queueFlags&VK_QUEUE_COMPUTE_BIT)&&!(p->queueFlags&VK_QUEUE_GRAPHICS_BIT)&&p->queueCount>1)p->queueCount--;}
static VkInstance instance_of(VkPhysicalDevice physical){
 VkInstance instance=VK_NULL_HANDLE;pthread_mutex_lock(&mutex);for(struct physical_state*p=physicals;p;p=p->link)if(p->physical==physical){instance=p->instance;break;}pthread_mutex_unlock(&mutex);return instance;
}
static void VKAPI_CALL queue_families(VkPhysicalDevice physical,uint32_t*count,VkQueueFamilyProperties*out){
 VkInstance instance=instance_of(physical);PFN_vkGetInstanceProcAddr next=instance?instance_next(instance):NULL;if(!next){*count=0;return;}
 ((PFN_vkGetPhysicalDeviceQueueFamilyProperties)next(instance,"vkGetPhysicalDeviceQueueFamilyProperties"))(physical,count,out);
 if(out)for(uint32_t i=0;i<*count;i++)hide_pace_queue(&out[i]);
}
static void queue_families2(VkPhysicalDevice physical,uint32_t*count,VkQueueFamilyProperties2*out,const char*name){
 VkInstance instance=instance_of(physical);PFN_vkGetInstanceProcAddr next=instance?instance_next(instance):NULL;PFN_vkGetPhysicalDeviceQueueFamilyProperties2 fn=next?(void*)next(instance,name):NULL;if(!fn){*count=0;return;}
 fn(physical,count,out);if(out)for(uint32_t i=0;i<*count;i++)hide_pace_queue(&out[i].queueFamilyProperties);
}
static void VKAPI_CALL queue_families2_core(VkPhysicalDevice p,uint32_t*n,VkQueueFamilyProperties2*o){queue_families2(p,n,o,"vkGetPhysicalDeviceQueueFamilyProperties2");}
static void VKAPI_CALL queue_families2_khr(VkPhysicalDevice p,uint32_t*n,VkQueueFamilyProperties2*o){queue_families2(p,n,o,"vkGetPhysicalDeviceQueueFamilyProperties2KHR");}
static void features2(VkPhysicalDevice physical,VkPhysicalDeviceFeatures2*f,const char*name){
 VkInstance instance=instance_of(physical);PFN_vkGetInstanceProcAddr next=instance?instance_next(instance):NULL;PFN_vkGetPhysicalDeviceFeatures2 fn=next?(void*)next(instance,name):NULL;if(!fn)return;
 fn(physical,f);if(!pace_wanted())return;
 for(VkBaseOutStructure*p=(void*)f->pNext;p;p=p->pNext){
  if(p->sType==VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PRESENT_WAIT_FEATURES_KHR)((VkPhysicalDevicePresentWaitFeaturesKHR*)p)->presentWait=VK_FALSE;
  if(p->sType==VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PRESENT_WAIT_2_FEATURES_KHR)((VkPhysicalDevicePresentWait2FeaturesKHR*)p)->presentWait2=VK_FALSE;
 }
}
static void VKAPI_CALL features2_core(VkPhysicalDevice p,VkPhysicalDeviceFeatures2*f){features2(p,f,"vkGetPhysicalDeviceFeatures2");}
static void VKAPI_CALL features2_khr(VkPhysicalDevice p,VkPhysicalDeviceFeatures2*f){features2(p,f,"vkGetPhysicalDeviceFeatures2KHR");}
/* Adds the reserved queue to a device create info. Returns the family, or -1 when pacing stays off for this device. */
static int pace_queue_request(VkInstance instance,VkPhysicalDevice physical,PFN_vkGetInstanceProcAddr next_i,const VkDeviceCreateInfo*info,
                              VkDeviceCreateInfo*ci,VkDeviceQueueCreateInfo qci[17],float prio[64],uint32_t*index){
 if(!pace_wanted()||pace_app_queue()||info->queueCreateInfoCount>=16)return -1;
 PFN_vkGetPhysicalDeviceQueueFamilyProperties qfp=(void*)next_i(instance,"vkGetPhysicalDeviceQueueFamilyProperties");if(!qfp)return -1;
 uint32_t nf=0;VkQueueFamilyProperties fp[16];qfp(physical,&nf,NULL);if(nf>16)nf=16;qfp(physical,&nf,fp);
 int family=-1;for(uint32_t i=0;i<nf;i++)if((fp[i].queueFlags&VK_QUEUE_COMPUTE_BIT)&&!(fp[i].queueFlags&VK_QUEUE_GRAPHICS_BIT)&&fp[i].queueCount>1){family=(int)i;break;}
 if(family<0)return -1;
 uint32_t n=info->queueCreateInfoCount;memcpy(qci,info->pQueueCreateInfos,n*sizeof(*qci));int found=-1;
 for(uint32_t i=0;i<n;i++)if(qci[i].queueFamilyIndex==(uint32_t)family)found=(int)i;
 if(found<0){prio[0]=1.0f;qci[n++]=(VkDeviceQueueCreateInfo){VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,NULL,0,(uint32_t)family,1,prio};*index=0;}
 else{if(qci[found].flags||qci[found].queueCount>=fp[family].queueCount||qci[found].queueCount>=63)return -1;
  for(uint32_t k=0;k<qci[found].queueCount;k++)prio[k]=qci[found].pQueuePriorities[k];
  *index=qci[found].queueCount;prio[*index]=1.0f;qci[found].queueCount++;qci[found].pQueuePriorities=prio;}
 *ci=*info;ci->queueCreateInfoCount=n;ci->pQueueCreateInfos=qci;return family;
}
