/* SPDX-License-Identifier: MIT
 * Private adapter using the probe's arithmetic and scoped resource ownership.
 * Tester builds qualify scaling separately and retain full-resolution fallback.
 */
/* Intel-free add-on (release/INTEL-FREE.md): only this project's shaders replace Intel's; a feature that needs an
 * Intel-derived shader is compiled out as a whole rather than mixed with Intel's originals. */
#include "probe_core.h"
#include "profile_manifest.h"
/* The shaders probe.c's compute_hook may replace by hash: exactly the <hash>.dxil files of the profile manifest. */
static int profile_lists_replacement(uint64_t shader){
 char name[24];snprintf(name,sizeof(name),"%016llx.dxil",(unsigned long long)shader);
 for(UINT i=0;i<sizeof(fast_files)/sizeof(*fast_files);i++)if(!strcmp(fast_files[i].name,name))return 1;
 return 0;
}
#include "timing.h"
#include "f4q.h"
#include "mfg_pipeline_cache.h"
static void proxy_pair_note(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,ID3D12PipelineState*);static void proxy_owner_released(void);
static UINT fast_scope;
static LONG fast_claimed;
static SRWLOCK fast_record_lock=SRWLOCK_INIT;
static SRWLOCK fast_lifecycle_lock=SRWLOCK_INIT;
/* Called only after successful SDK destruction and confirmed GPU completion.
 * Counts alone are insufficient: reused slots contain descriptor/root state. */
static void fast_reset_tracking(void){
 mfg_pool_release();mfg_release_pipeline_cache();
 memset(flow_lists,0,sizeof(flow_lists));flow_list_count=0;flow_cap_enabled=0;flow_frames=0;
 memset(flow_psos,0,sizeof(flow_psos));flow_pso_count=0;
 memset(psos,0,sizeof(psos));npsos=0;
 memset(bindings,0,sizeof(bindings));nbinding=0;
 memset(split_z,0,sizeof(split_z));split_count=0;
 memset(models,0,sizeof(models));model_count=0;model_allocations_open=0;model_device=NULL;
 memset(model_descriptors,0,sizeof(model_descriptors));model_descriptor_count=0;
 memset(model_heaps,0,sizeof(model_heaps));model_heap_count=0;
 memset(model_lists,0,sizeof(model_lists));model_list_count=0;
 memset(model_roots,0,sizeof(model_roots));memset(model_graph_roots,0,sizeof(model_graph_roots));model_root_count=0;
 memset(graph_prepare,0,sizeof(graph_prepare));memset(graph_multiply,0,sizeof(graph_multiply));
 memset(graph_finish_mfg,0,sizeof(graph_finish_mfg));
 memset(graph_finish,0,sizeof(graph_finish));memset(graph_finish_coarse17,0,sizeof(graph_finish_coarse17));
 memset(graph_input,0,sizeof(graph_input));memset(graph_output,0,sizeof(graph_output));memset(graph_capacity,0,sizeof(graph_capacity));
 memset(graph_retired,0,sizeof(graph_retired));graph_retired_count=0;
 memset(graph_lists,0,sizeof(graph_lists));graph_list_count=0;
 memset(graph_counts,0,sizeof(graph_counts));memset(graph_profiles,0,sizeof(graph_profiles));memset(graph_coarse17_profiles,0,sizeof(graph_coarse17_profiles));
 graph_logged=0;graph_ready=0;graph_enabled=0;graph_adaptive=0;graph_coarse17=0;graph_geometry_fallbacks=0;
 graph_refine_columns=48;graph_refine_pad=0;graph_device=NULL;graph_root=NULL;graph_queue=NULL;
}
static HRESULT STDMETHODCALLTYPE fast_compute(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,REFIID iid,void**out){
 AcquireSRWLockExclusive(&fast_record_lock);HRESULT hr;
 hr=mfg_cached_compute(d,desc,iid,out);
 if(SUCCEEDED(hr))proxy_pair_note(d,desc,*out);  /* beside another module: Intel's original next to a replacement */
 ReleaseSRWLockExclusive(&fast_record_lock);return hr;
}
static void STDMETHODCALLTYPE fast_set(ID3D12GraphicsCommandList*l,ID3D12PipelineState*p){
 AcquireSRWLockExclusive(&fast_record_lock);set_hook(l,p);ReleaseSRWLockExclusive(&fast_record_lock);
}
static void STDMETHODCALLTYPE fast_dispatch(ID3D12GraphicsCommandList*l,UINT x,UINT y,UINT z){
 AcquireSRWLockExclusive(&fast_record_lock);
 /* F4Q's check (diagnostic, f4q.h): the F(4x4) kernel and its fingerprint before the runtime's dispatch, the F(2x2)
  * kernel's fingerprint and the comparison after it */
 uint64_t fq_shader=0;if(fq.on&&!fq.stopped){for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)for(LONG s=0;s<npsos;s++)if(psos[s].p==bindings[b].p)fq_shader=psos[s].hash;fq_before(l,fq_shader,x,y,z);}
 dispatch_hook(l,x,y,z);
 if(fq_shader)fq_after(l,fq_shader);
 tracing=0;ReleaseSRWLockExclusive(&fast_record_lock);
}
static int fast_profile_file(const char*path,UINT64 bytes,uint64_t expected){
 HANDLE f=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);if(f==INVALID_HANDLE_VALUE)return 0;
 LARGE_INTEGER size;int ok=GetFileSizeEx(f,&size)&&size.QuadPart==bytes;unsigned char data[1024];DWORD n;uint64_t h=0xcbf29ce484222325ULL;UINT64 total=0;
 while(ok&&total<bytes){if(!ReadFile(f,data,sizeof(data),&n,NULL)||!n){ok=0;break;}total+=n;for(DWORD i=0;i<n;i++)h=h*0x100000001b3ULL^data[i];}
 CloseHandle(f);return ok&&total==bytes&&h==expected;
}
/* BC250_XEFG_ANY_GPU=1 (also on/true/yes) lets an adapter other than the BC-250 take the accelerated path. */
static int fast_any_gpu(void){
 char v[8];DWORD n=GetEnvironmentVariableA("BC250_XEFG_ANY_GPU",v,sizeof(v));if(!n||n>=sizeof(v))return 0;
 return !strcmp(v,"1")||!lstrcmpiA(v,"on")||!lstrcmpiA(v,"true")||!lstrcmpiA(v,"yes");
}
static int fast_candidate(ID3D12Device*d,void*caller){
 HMODULE caller_module=NULL;char caller_name[1024]={0},owner[128]={0};
 GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,(const char*)caller,&caller_module);
 if(caller_module)GetModuleFileNameA(caller_module,caller_name,sizeof(caller_name));
 proxy_log("CONTEXT_CALLER ");proxy_log(caller_name);proxy_log("\n");
 DWORD owner_size=GetEnvironmentVariableA("BC250_XEFG_OWNER_MODULE",owner,sizeof(owner));
 if(owner_size&&(owner_size>=sizeof(owner)||!caller_module||GetModuleHandleA(owner)!=caller_module)){
  proxy_log("FAST_SKIP context belongs to another integration\n");return 0;
 }
 char disabled[16];if(GetEnvironmentVariableA("BC250_XEFG_DISABLE",disabled,sizeof(disabled))&&!strcmp(disabled,"1"))return 0;
 if(InterlockedCompareExchange(&fast_claimed,0,0))return 0;
 DWORD size=GetEnvironmentVariableA("XEFG_GAME_PROFILE",patchdir,sizeof(patchdir));
 if(!size){
  static wchar_t path[1100];if(wcslen(proxy_directory)+40>=1100)return 0;
  wcscpy(path,proxy_directory);wcscat(path,L"BC250-XeFG\\shaders");BOOL lost=FALSE;
  if(!WideCharToMultiByte(CP_ACP,WC_NO_BEST_FIT_CHARS,path,-1,patchdir,sizeof(patchdir),NULL,&lost)||lost)return 0;
 }else if(size>=sizeof(patchdir))return 0;
 HMODULE dxgi=GetModuleHandleA("dxgi.dll");if(!dxgi)return 0;
 HRESULT(WINAPI*create)(UINT,REFIID,void**)=(void*)GetProcAddress(dxgi,"CreateDXGIFactory2");if(!create)return 0;
 IDXGIFactory4*factory=NULL;IDXGIAdapter1*adapter=NULL;DXGI_ADAPTER_DESC1 desc={0};
 if(FAILED(create(0,&IID_IDXGIFactory4,(void**)&factory)))return 0;
 LUID luid=ID3D12Device_GetAdapterLuid(d);HRESULT hr=IDXGIFactory4_EnumAdapterByLuid(factory,luid,&IID_IDXGIAdapter1,(void**)&adapter);IDXGIFactory4_Release(factory);
 if(FAILED(hr))return 0;hr=IDXGIAdapter1_GetDesc1(adapter,&desc);IDXGIAdapter1_Release(adapter);
 if(FAILED(hr)){proxy_log("FAST_FALLBACK requires BC250 adapter\n");return 0;}
 if(desc.VendorId!=0x1002||desc.DeviceId!=0x13fe){
  /* Another GPU runs Intel's shaders unless its user opts in (BC250_XEFG_ANY_GPU=1): the profile, prepared network and
   * scaling then run on hardware nobody has qualified, and the model/layout guards end the game on a contract they do
   * not recognise. */
  char line[200];int any=fast_any_gpu();
  snprintf(line,sizeof(line),any?"FAST_ANY_GPU adapter %04x:%04x: BC250 acceleration on untested hardware (BC250_XEFG_ANY_GPU=1)\n":
           "FAST_FALLBACK requires BC250 adapter (this one is %04x:%04x; BC250_XEFG_ANY_GPU=1 tries it anyway)\n",desc.VendorId,desc.DeviceId);
  proxy_log(line);if(!any)return 0;
 }
 char file[1200];
 for(UINT i=0;i<sizeof(fast_files)/sizeof(*fast_files);i++){
  snprintf(file,sizeof(file),"%s\\%s",patchdir,fast_files[i].name);
  if(!fast_profile_file(file,fast_files[i].size,fast_files[i].hash)){proxy_log("FAST_FALLBACK profile verification failed: ");proxy_log(fast_files[i].name);proxy_log("\n");return 0;}
 }
 return 1;
}
static __attribute__((noinline)) int fast_prepare(ID3D12Device*d){
 static wchar_t path[1100];if(wcslen(proxy_directory)+32>=1100)return 0;
 wcscpy(path,proxy_directory);wcscat(path,L"BC250-XeFG-fast.log");
 /* One log per game session: the first context of this process starts it afresh (Setup's status reads it as the last
  * session, and it would otherwise grow forever); later contexts append. */
 static LONG fast_log_started;
 output=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,InterlockedExchange(&fast_log_started,1)?OPEN_ALWAYS:CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
 if(output==INVALID_HANDLE_VALUE)return 0;
 SetFilePointer(output,0,NULL,FILE_END);logline("FAST_CONTEXT_BEGIN\n");
 game_timing_prepare(d);
 char scale[1200];snprintf(scale,sizeof(scale),"%s\\dispatch-scale.txt",patchdir);load_dispatch_scale(scale,1);
 ID3D12CommandAllocator*a=NULL;ID3D12GraphicsCommandList*l=NULL;ID3D12CommandQueue*q=NULL;
 D3D12_COMMAND_QUEUE_DESC desc={.Type=D3D12_COMMAND_LIST_TYPE_DIRECT};
 HR(ID3D12Device_CreateCommandAllocator(d,0,&IID_ID3D12CommandAllocator,(void**)&a));
 HR(ID3D12Device_CreateCommandList(d,0,0,a,NULL,&IID_ID3D12GraphicsCommandList,(void**)&l));
 HR(ID3D12GraphicsCommandList_Close(l));
 HR(ID3D12Device_CreateCommandQueue(d,&desc,&IID_ID3D12CommandQueue,(void**)&q));
 compute_original=d->lpVtbl->CreateComputePipelineState;
 replace((void*)&d->lpVtbl->CreateComputePipelineState,fast_compute);
 install_model_owner(d,l);
 f4q_configure();  /* F4Q's switch and layout check, before the runtime creates a model or pipeline (src/model_f4q.h) */
 mfg_scaling_suppressed=0;
 if(f4q_mode==F4Q_SHADOW&&env_uint("XEFG_FLOW_CAP",0)){
  mfg_scaling_suppressed=1;
  logline("FREEFG_SCALE fallback: F4Q shadow diagnostic requires full output; full output retained\n");
 }
 scale_install(env_uint("XEFG_FLOW_CAP",0));
 set_original=l->lpVtbl->SetPipelineState;dispatch_original=l->lpVtbl->Dispatch;
 replace((void*)&l->lpVtbl->SetPipelineState,fast_set);replace((void*)&l->lpVtbl->Dispatch,fast_dispatch);
 install_graph(d,q);
 fq_install(d,l);  /* F4Q's check only: root, descriptor and heap tracking for its own compare passes */
 install_flow_cap(l,0,0);
 ID3D12CommandQueue_Release(q);ID3D12GraphicsCommandList_Release(l);ID3D12CommandAllocator_Release(a);
 fast_scope=((struct scoped_com*)d)->scope;
 logline("PRIVATE GAME TRIAL scoped prepared-model and Winograd path installed\n");
 logline("INTEL_FREE own shaders only; Intel's original pipelines elsewhere\n");
 return 1;
}
static UINT fast_context_scope(xefg_swapchain_handle_t handle){
 if(!handle)return 0;  /* free slots hold NULL handles */
 UINT scope=0;AcquireSRWLockShared(&scoped_lock);for(UINT i=0;i<16;i++)if(scoped_contexts[i].handle==handle)scope=scoped_contexts[i].scope;ReleaseSRWLockShared(&scoped_lock);return scope;
}
static void fast_begin_init(xefg_swapchain_handle_t handle){
 if(!handle)return;  /* the SDK rejects it; a free slot must not match */
 AcquireSRWLockExclusive(&fast_lifecycle_lock);
 struct scoped_com*d=NULL;AcquireSRWLockShared(&scoped_lock);
 for(UINT i=0;i<16;i++)if(scoped_contexts[i].handle==handle){d=scoped_contexts[i].device;scoped_addref(d);break;}
 ReleaseSRWLockShared(&scoped_lock);
 if(d&&!InterlockedCompareExchange(&fast_claimed,1,0)){
  if(fast_prepare((void*)d))proxy_log("FAST_OWNER first initialized context selected\n");
 }
 if(d)scoped_release(d);ReleaseSRWLockExclusive(&fast_lifecycle_lock);
}
static void fast_ready(xefg_swapchain_handle_t handle){if(fast_scope&&fast_context_scope(handle)==fast_scope&&!graph_ready){model_seal_allocations();if(!proxy_aside_active())graph_initialize();}}
static void fast_report(xefg_swapchain_handle_t handle){
 if(fast_scope&&fast_context_scope(handle)==fast_scope)frame_report();
 if(fast_scope&&fast_context_scope(handle)==fast_scope){char line[120];snprintf(line,sizeof(line),"FLOW_CAP frames=%llu\n",(unsigned long long)flow_frames);logline(line);}
if(fast_scope&&fast_context_scope(handle)==fast_scope){game_timing_dump();graph_report();
 char pool_line[160];snprintf(pool_line,sizeof(pool_line),"MFG_POOL unique=%u reused=%llu aliases=%u pipelines=%u pipeline_hits=%llu roots=%u\n",model_count,(unsigned long long)mfg_pool_hits,mfg_alias_count,mfg_pipeline_count,(unsigned long long)mfg_pipeline_hits,mfg_root_cache_count);logline(pool_line);
 char tracking_line[240];snprintf(tracking_line,sizeof(tracking_line),"MFG_TRACKING heaps=%u descriptors=%u model_lists=%u flow_lists=%u frame_lists=%u graph_lists=%u bindings=%u\n",model_heap_count,model_descriptor_count,model_list_count,flow_list_count,frame_list_count,graph_list_count,nbinding);logline(tracking_line);
}}
static void fast_finish(xefg_swapchain_handle_t handle){
 if(!handle)return;
 UINT scope=0;AcquireSRWLockShared(&scoped_lock);
 for(UINT i=0;i<16;i++)if(scoped_contexts[i].handle==handle)scope=scoped_contexts[i].scope;
 ReleaseSRWLockShared(&scoped_lock);if(!fast_scope||scope!=fast_scope)return;
 if(graph_queue){
  ID3D12Fence*fence=NULL;HANDLE event=CreateEventA(NULL,FALSE,FALSE,NULL);int idle=0;
  if(event&&SUCCEEDED(ID3D12Device_CreateFence(model_device,0,0,&IID_ID3D12Fence,(void**)&fence))&&SUCCEEDED(ID3D12CommandQueue_Signal(graph_queue,fence,1))&&SUCCEEDED(ID3D12Fence_SetEventOnCompletion(fence,1,event)))idle=WaitForSingleObject(event,10000)==WAIT_OBJECT_0;
  if(fence)ID3D12Fence_Release(fence);if(event)CloseHandle(event);
  if(!idle){proxy_log("FAST_RETAIN GPU completion unconfirmed; resources held until process exit\n");return;}
 }
 frame_release();
 for(UINT i=0;i<flow_pso_count;i++)ID3D12PipelineState_Release(flow_psos[i].capped);
 for(UINT i=0;i<3;i++){if(graph_prepare[i])ID3D12PipelineState_Release(graph_prepare[i]);if(graph_multiply[i])ID3D12PipelineState_Release(graph_multiply[i]);}
 game_timing_release();
 for(UINT i=0;i<4;i++)if(graph_finish[i])ID3D12PipelineState_Release(graph_finish[i]);
 for(UINT i=0;i<5;i++)if(graph_finish_mfg[i])ID3D12PipelineState_Release(graph_finish_mfg[i]);
 for(UINT i=0;i<3;i++)if(graph_ref64_pso[i]){ID3D12PipelineState_Release(graph_ref64_pso[i]);graph_ref64_pso[i]=NULL;}
 for(UINT i=0;i<2;i++){if(graph_finish_coarse17[i])ID3D12PipelineState_Release(graph_finish_coarse17[i]);if(graph_input[i])ID3D12Resource_Release(graph_input[i]);if(graph_output[i])ID3D12Resource_Release(graph_output[i]);}
 for(UINT i=0;i<graph_retired_count;i++)ID3D12Resource_Release(graph_retired[i]);
 for(LONG i=0;i<npsos;i++)ID3D12PipelineState_Release((ID3D12PipelineState*)psos[i].p);
 for(UINT i=0;i<model_count;i++){if(models[i].upload)ID3D12Resource_Release(models[i].upload);ID3D12Resource_Release(models[i].r);}
 for(UINT i=0;i<model_root_count;i++)ID3D12RootSignature_Release(model_roots[i]);
 mfg_release_roots();
 if(graph_queue)ID3D12CommandQueue_Release(graph_queue);
 /* Restore this context's private forwarding before allowing a fresh owner. */
 AcquireSRWLockExclusive(&scoped_lock);
 for(UINT i=0;i<16;i++)if(scoped_contexts[i].handle==handle){struct scoped_tables*t=scoped_contexts[i].device->tables;memcpy(t->device,scoped_device_vtable,sizeof(t->device));memcpy(t->list,scoped_list_vtable,sizeof(t->list));memcpy(t->queue,scoped_queue_vtable,sizeof(t->queue));break;}
 ReleaseSRWLockExclusive(&scoped_lock);fast_scope=0;fq_finish();CloseHandle(output);output=INVALID_HANDLE_VALUE;  /* F4Q: its last lines before the log closes */
 proxy_log("FAST_RELEASED GPU completion verified; private resources released\n");
 fast_reset_tracking();
 proxy_owner_released();
 InterlockedExchange(&fast_claimed,0);
}
