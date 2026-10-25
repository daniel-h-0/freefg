/* SPDX-License-Identifier: MIT
 * CPU-only unit test of the multi-frame proxy's bookkeeping beside another module hooking Intel's runtime
 * (src/game/mfg_proxy_coexist.h), run under Wine by release/check_proxy_wine.py --variant intel-free-mfg. It includes
 * that header and the real scoped forwarding objects (scoped_com.h) with stand-ins for the rest of the add-on (no
 * D3D12 device, no Intel runtime, no GPU): fake COM objects count their references, and Intel's runtime is a function
 * that answers xefgSwapChainD3D12GetInitializationParameters. The program carries a version resource whose product is
 * OptiScaler (check_proxy_wine.py links it in), so a call from its own code counts as OptiScaler's.
 *
 * Checked: only OptiScaler's contexts are scoped; a creation is claimed by the output pointer that holds the handle,
 * else by the initialisation queue's device when one pending creation matches, never when several do; a context
 * destroyed before its initialisation is claimed and released; four pending creations at most, none evicted; an
 * output pointer reused replaces its unclaimed entry; the deferred initialisation work runs at the first call after the
 * initialisation (once) and not for a context whose initialisation failed; the frame count of a maximum-count
 * initialisation is learned; no status read for a NULL handle; at the end every reference this proxy took on the fake
 * device and queue is released and nothing is left pending.
 */
#define WIDL_C_INLINE_WRAPPERS
#define COBJMACROS
#define INITGUID
#include <windows.h>
#include <d3d12.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <xefg_swapchain_d3d12.h>
int _fltused;

/* ------------------------------------------------------------------------------ stand-ins for the rest of the add-on */
static HANDLE out;
static char log_text[65536];static size_t log_size;
static void proxy_log(const char*s){size_t n=strlen(s);if(log_size+n<sizeof(log_text)){memcpy(log_text+log_size,s,n);log_size+=n;log_text[log_size]=0;}}
static void logline(const char*s){proxy_log(s);}
static HMODULE proxy_module,original_module;
static volatile LONG64 proxy_status_generated;
static volatile LONG proxy_status_multiplier;
static UINT env_uint(const char*k,UINT v){(void)k;return v;}
static void mfg_tag_capture(xefg_swapchain_handle_t h){(void)h;}
static void mfg_settings_note_context(xefg_swapchain_handle_t h){(void)h;}
static void mfg_settings_clear_context(void){}
static int init_answer,init_calls,resolves;
static UINT init_max=5;
static xefg_swapchain_result_t intel_init_parameters(xefg_swapchain_handle_t h,xefg_swapchain_d3d12_init_params_t*p){
 (void)h;init_calls++;if(init_answer)return init_answer;p->maxInterpolatedFrames=init_max;return XEFG_SWAPCHAIN_RESULT_SUCCESS;}
static FARPROC resolve(const char*name){resolves++;return !strcmp(name,"xefgSwapChainD3D12GetInitializationParameters")?(FARPROC)intel_init_parameters:NULL;}
/* probe core */
static struct{ID3D12GraphicsCommandList*l;ID3D12PipelineState*p;} bindings[4];static UINT nbinding;
static void(STDMETHODCALLTYPE*set_original)(ID3D12GraphicsCommandList*,ID3D12PipelineState*);
static void(STDMETHODCALLTYPE*dispatch_original)(ID3D12GraphicsCommandList*,UINT,UINT,UINT);
static HRESULT(STDMETHODCALLTYPE*compute_original)(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,REFIID,void**);
static uint64_t hash(const void*d,SIZE_T n){(void)d;(void)n;return 0;}
static int profile_lists_replacement(uint64_t s){(void)s;return 0;}
static int graph_ready,graph_enabled;static ID3D12CommandQueue*graph_queue;static ID3D12Device*model_device;
static UINT frame_output_count,mfg_second_phase_pending,mfg_live_heap_count,frame_desc_count;static SRWLOCK frame_lock=SRWLOCK_INIT;
static UINT64 mfg_retired_heaps,mfg_retired_lists,mfg_retired_queues;
static void frame_release_output_views(void){}
#include "scoped_com.h"  /* with XEFG_MFG_RETIRE, which check_proxy_wine.py defines as the proxy build does */
static int collected;
static void mfg_retire_scoped(struct scoped_com*p){(void)p;collected++;}
/* fast_trial.h */
static UINT fast_scope;static SRWLOCK fast_record_lock=SRWLOCK_INIT,fast_lifecycle_lock=SRWLOCK_INIT;
static int candidate_answer,candidates,readies,finishes;
static int fast_candidate(ID3D12Device*d,void*caller){(void)d;(void)caller;candidates++;return candidate_answer;}
static UINT fast_context_scope(xefg_swapchain_handle_t handle){
 if(!handle)return 0;UINT scope=0;AcquireSRWLockShared(&scoped_lock);for(UINT i=0;i<16;i++)if(scoped_contexts[i].handle==handle)scope=scoped_contexts[i].scope;ReleaseSRWLockShared(&scoped_lock);return scope;}
static void fast_begin_init(xefg_swapchain_handle_t handle){if(handle&&!fast_scope)fast_scope=fast_context_scope(handle);}  /* the first scoped context owns */
static void fast_ready(xefg_swapchain_handle_t handle){if(fast_scope&&fast_context_scope(handle)==fast_scope)readies++;}
static void fast_report(xefg_swapchain_handle_t handle){(void)handle;}
static void proxy_owner_released(void);
static void fast_finish(xefg_swapchain_handle_t handle){if(fast_scope&&fast_context_scope(handle)==fast_scope){fast_scope=0;finishes++;proxy_owner_released();}}
/* f4q.h */
static void fq_frame_tick(void){}
#include "mfg_proxy_coexist.h"

/* --------------------------------------------------------------------------------------------- fake COM objects */
struct fake{void**vtable;LONG refs;struct fake*device;};
static HRESULT STDMETHODCALLTYPE fake_query(struct fake*f,REFIID iid,void**result){(void)iid;InterlockedIncrement(&f->refs);*result=f;return S_OK;}
static ULONG STDMETHODCALLTYPE fake_addref(struct fake*f){return InterlockedIncrement(&f->refs);}
static ULONG STDMETHODCALLTYPE fake_release(struct fake*f){return InterlockedDecrement(&f->refs);}
static HRESULT STDMETHODCALLTYPE fake_get_device(struct fake*q,REFIID iid,void**result){(void)iid;fake_addref(q->device);*result=q->device;return S_OK;}
static void*device_vtable[SCOPED_device_COUNT],*queue_vtable[SCOPED_queue_COUNT];
static struct fake device={device_vtable,1,NULL},other_device={device_vtable,1,NULL},queue={queue_vtable,1,&device},other_queue={queue_vtable,1,&other_device};

/* --------------------------------------------------------------------------------------------------------- checks */
static int failures;
static void check(int ok,const char*what,int line){char text[300];snprintf(text,sizeof(text),"%s line=%d: %s\n",ok?"ok":"FAIL",line,what);DWORD n;WriteFile(out,text,(DWORD)strlen(text),&n,NULL);failures+=!ok;}
#define CHECK(x) check((x)!=0,#x,__LINE__)
static int logged(const char*s){return strstr(log_text,s)!=NULL;}
static int count_logged(const char*s){int n=0;for(const char*p=log_text;(p=strstr(p,s));p+=strlen(s))n++;return n;}
#define H(n) ((xefg_swapchain_handle_t)(uintptr_t)(0x1000*(n)))
static __attribute__((noinline)) void*here(void){return __builtin_return_address(0);}  /* an address in this program */

void mainCRTStartup(void){
 out=GetStdHandle(STD_OUTPUT_HANDLE);
 device_vtable[0]=fake_query;device_vtable[1]=fake_addref;device_vtable[2]=fake_release;
 queue_vtable[0]=fake_query;queue_vtable[1]=fake_addref;queue_vtable[2]=fake_release;queue_vtable[SCOPED_queue_GetDevice]=fake_get_device;
 ID3D12Device*D=(ID3D12Device*)&device,*D2=(ID3D12Device*)&other_device;ID3D12CommandQueue*Q=(ID3D12CommandQueue*)&queue,*Q2=(ID3D12CommandQueue*)&other_queue;
 void*self=here();void*system=(void*)GetProcAddress(GetModuleHandleA("kernel32.dll"),"Sleep");
 xefg_swapchain_handle_t a=NULL,b=NULL,c=NULL,d=NULL,e=NULL,f[5]={0};

 /* Version resources: this program's names OptiScaler, kernel32's does not. */
 CHECK(proxy_module_is_optiscaler(GetModuleHandleA(NULL)));
 CHECK(!proxy_module_is_optiscaler(GetModuleHandleA("kernel32.dll")));
 CHECK(!proxy_module_is_optiscaler(NULL));

 /* Only OptiScaler's contexts reach the candidate check; another module's keep the caller's device. */
 CHECK(proxy_create_foreign(D,&a,system)==NULL);CHECK(candidates==0);CHECK(logged("(created from kernel32.dll)"));
 CHECK(proxy_create_foreign(D,&a,NULL)==NULL);CHECK(candidates==0);CHECK(logged("(created from code outside any module)"));
 CHECK(proxy_create_foreign(D,&a,self)==NULL);CHECK(candidates==1);  /* OptiScaler's, but not a candidate */
 CHECK(proxy_deferred==0);CHECK(device.refs==1);

 /* Claimed by its output pointer; the deferred work runs once, at the first call after the initialisation. */
 candidate_answer=1;
 ID3D12Device*s1=proxy_create_foreign(D,&a,self);CHECK(s1&&s1!=D);CHECK(proxy_deferred==1);CHECK(device.refs==2);
 a=H(1);  /* Intel writes the handle */
 xefg_swapchain_d3d12_init_params_t maximum={.maxInterpolatedFrames=XEFG_SWAPCHAIN_USE_MAX_SUPPORTED_INTERPOLATED_FRAMES};
 proxy_frames_init(H(1),&maximum);
 ID3D12CommandQueue*q1=proxy_init_foreign(H(1),Q);
 CHECK(fast_context_scope(H(1)));CHECK(fast_scope==fast_context_scope(H(1)));CHECK(proxy_owner_foreign);
 CHECK(q1&&q1!=Q);CHECK(queue.refs==2);CHECK(proxy_deferred==1);CHECK(readies==0);
 proxy_ready_first(H(2));CHECK(readies==0);CHECK(init_calls==0);  /* another handle */
 proxy_ready_first(H(1));CHECK(readies==1);CHECK(init_calls==1);CHECK(proxy_deferred==0);
 proxy_ready_first(H(1));proxy_frame_tick(H(1));CHECK(readies==1);CHECK(init_calls==1);
 CHECK(logged("MFG_FACTOR the runtime's maximum for this context is 6x"));
 /* A frame-count change after it retires (the first SetNumInterpolatedFrames is a change from the maximum). */
 proxy_frames_changed(H(1),2);CHECK(logged("MFG_FACTOR 3x"));CHECK(count_logged("MFG_RETIRED")==1);
 proxy_frames_changed(H(1),2);CHECK(count_logged("MFG_RETIRED")==1);
 /* No status read for a NULL handle. */
 int before=resolves;proxy_status_poll(NULL);CHECK(resolves==before);
 /* The layer follows the actual SDK output count, including a decrease; an empty status is not generation. */
 xefg_swapchain_present_status_t status={0};
 status.framesPresented=4;proxy_status_count(&status);CHECK(proxy_status_multiplier==4);
 status.framesPresented=2;proxy_status_count(&status);CHECK(proxy_status_multiplier==2);
 status.framesPresented=0;proxy_status_count(&status);proxy_status_count(NULL);CHECK(proxy_status_multiplier==2);
 /* Destroyed: released at the next creation, with every reference on the device and queue. */
 proxy_frames_forget(H(1));proxy_destroy_foreign(H(1));CHECK(proxy_deferred==1);CHECK(device.refs==2);
 candidate_answer=0;CHECK(proxy_create_foreign(D,&b,self)==NULL);
 CHECK(finishes==1);CHECK(!fast_scope);CHECK(!proxy_owner_foreign);CHECK(proxy_deferred==0);CHECK(device.refs==1);CHECK(queue.refs==1);

 /* Claimed by its device when the output pointer no longer holds the handle (one creation on that device). */
 candidate_answer=1;CHECK(proxy_create_foreign(D,&b,self)!=NULL);CHECK(proxy_create_foreign(D2,&c,self)!=NULL);
 b=(void*)0x77;c=H(3);  /* b was moved elsewhere by its caller */
 CHECK(proxy_init_foreign(H(2),Q)!=NULL);CHECK(fast_context_scope(H(2)));CHECK(logged("matched by its device"));CHECK(proxy_deferred==2);
 CHECK(proxy_init_foreign(H(3),Q2)!=NULL);CHECK(fast_context_scope(H(3)));  /* by its output pointer */
 CHECK(device.refs==2);CHECK(other_device.refs==2);
 /* The initialisation of H(3) did not succeed: nothing is prepared for it. H(2) owns. */
 init_answer=-1;proxy_ready_first(H(3));CHECK(logged("did not succeed"));init_answer=0;
 proxy_ready_first(H(2));CHECK(readies==2);CHECK(proxy_deferred==0);

 /* Two pending creations on one device, neither output pointer holding the handle: no claim, the caller's queue. */
 CHECK(proxy_create_foreign(D,&d,self)!=NULL);CHECK(proxy_create_foreign(D,&e,self)!=NULL);d=(void*)0x78;e=(void*)0x79;
 CHECK(proxy_init_foreign(H(4),Q)==NULL);CHECK(!fast_context_scope(H(4)));CHECK(logged("several pending creations matched none"));
 CHECK(proxy_deferred==2);
 /* A creation that reuses an output pointer replaces its unclaimed entry. */
 LONG refs=device.refs;CHECK(proxy_create_foreign(D,&d,self)!=NULL);CHECK(proxy_deferred==2);CHECK(device.refs==refs);
 /* Destroyed before its initialisation: claimed at destruction and released at the next creation. */
 d=H(5);proxy_destroy_foreign(H(5));CHECK(fast_context_scope(H(5)));CHECK(proxy_deferred==2);  /* e pending, H(5) finishing */
 /* At most four pending creations; none is evicted, the next one keeps the caller's device. */
 e=H(6);proxy_destroy_foreign(H(6));
 refs=device.refs;
 for(int i=0;i<4;i++)CHECK(proxy_create_foreign(D,&f[i],self)!=NULL);  /* also runs the two pending releases */
 CHECK(!fast_context_scope(H(5)));CHECK(!fast_context_scope(H(6)));CHECK(device.refs==refs-2+4);CHECK(proxy_deferred==4);
 refs=device.refs;CHECK(proxy_create_foreign(D,&f[4],self)==NULL);CHECK(logged("4 contexts await"));CHECK(device.refs==refs);
 for(int i=0;i<4;i++){f[i]=H(10+i);proxy_destroy_foreign(H(10+i));}

 /* The rest destroyed: every reference released, nothing pending. */
 proxy_destroy_foreign(H(2));proxy_destroy_foreign(H(3));proxy_finish_deferred(NULL);
 CHECK(proxy_deferred==0);CHECK(device.refs==1);CHECK(other_device.refs==1);CHECK(queue.refs==1);CHECK(other_queue.refs==1);
 CHECK(finishes==2);CHECK(collected>=0);

 char line[80];snprintf(line,sizeof(line),"COEXIST_UNIT failures=%d\n",failures);DWORD n;WriteFile(out,line,(DWORD)strlen(line),&n,NULL);
 WriteFile(out,"LOG\n",4,&n,NULL);WriteFile(out,log_text,(DWORD)log_size,&n,NULL);
 ExitProcess(failures?1:0);
}
