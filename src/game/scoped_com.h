/* SPDX-License-Identifier: MIT
 * SDK-private forwarding objects. The application's own vtables are untouched.
 * This first version observes SDK allocations/pipelines; it does not optimize. */
#include "com_thunks.h"
enum { SCOPED_DEVICE=1,SCOPED_LIST=2,SCOPED_QUEUE=3 };
struct scoped_tables {LONG refs;void*device[SCOPED_device_COUNT];void*list[SCOPED_list_COUNT];void*queue[SCOPED_queue_COUNT];};
struct scoped_com {void**vtable;IUnknown*real;LONG refs;UINT kind;UINT scope;struct scoped_com*next;struct scoped_tables*tables;};
_Static_assert(offsetof(struct scoped_com,real)==8,"x64 COM forwarding layout");
static void *scoped_device_vtable[SCOPED_device_COUNT],*scoped_list_vtable[SCOPED_list_COUNT],*scoped_queue_vtable[SCOPED_queue_COUNT];
static struct scoped_com*scoped_objects;
static SRWLOCK scoped_lock=SRWLOCK_INIT;
static INIT_ONCE scoped_once=INIT_ONCE_STATIC_INIT;
static LONG scoped_sequence;
static struct {xefg_swapchain_handle_t handle;UINT scope;struct scoped_com*device;} scoped_contexts[16];
static IUnknown*scoped_raw(IUnknown*object){
 IUnknown*result=object;AcquireSRWLockShared(&scoped_lock);
 for(struct scoped_com*p=scoped_objects;p;p=p->next)if((void*)p==(void*)object){result=p->real;break;}
 ReleaseSRWLockShared(&scoped_lock);return result;
}
static ULONG STDMETHODCALLTYPE scoped_addref(struct scoped_com*p){return InterlockedIncrement(&p->refs);}
static ULONG STDMETHODCALLTYPE scoped_release(struct scoped_com*p){
 ULONG refs=InterlockedDecrement(&p->refs);if(!refs){IUnknown_Release(p->real);if(!InterlockedDecrement(&p->tables->refs))HeapFree(GetProcessHeap(),0,p->tables);HeapFree(GetProcessHeap(),0,p);}return refs;
}
static void mfg_retire_scoped(struct scoped_com*);
/* Only the adapter's lifetime reference remains. The SDK has released every
 * external wrapper reference; active SDK lists/queues cannot enter this set. */
static void scoped_collect_idle(UINT scope){
 struct scoped_com*retired=NULL;AcquireSRWLockExclusive(&scoped_lock);
 struct scoped_com**link=&scoped_objects;while(*link){struct scoped_com*p=*link;
  if(p->scope==scope&&p->kind!=SCOPED_DEVICE&&InterlockedCompareExchange(&p->refs,0,0)==1){*link=p->next;p->next=retired;retired=p;}
  else link=&p->next;
 }
 ReleaseSRWLockExclusive(&scoped_lock);
 while(retired){struct scoped_com*p=retired;retired=p->next;mfg_retire_scoped(p);scoped_release(p);}
}
static int scoped_iid(UINT kind,REFIID iid){
 if(IsEqualGUID(iid,&IID_IUnknown)||IsEqualGUID(iid,&IID_ID3D12Object))return 1;
 if(kind==SCOPED_DEVICE)return IsEqualGUID(iid,&IID_ID3D12Device)||IsEqualGUID(iid,&IID_ID3D12Device1)||IsEqualGUID(iid,&IID_ID3D12Device2)||IsEqualGUID(iid,&IID_ID3D12Device3)||IsEqualGUID(iid,&IID_ID3D12Device4)||IsEqualGUID(iid,&IID_ID3D12Device5)||IsEqualGUID(iid,&IID_ID3D12Device6)||IsEqualGUID(iid,&IID_ID3D12Device7)||IsEqualGUID(iid,&IID_ID3D12Device8)||IsEqualGUID(iid,&IID_ID3D12Device9)||IsEqualGUID(iid,&IID_ID3D12Device10);
 if(IsEqualGUID(iid,&IID_ID3D12DeviceChild)||IsEqualGUID(iid,&IID_ID3D12Pageable))return 1;
 if(kind==SCOPED_QUEUE)return IsEqualGUID(iid,&IID_ID3D12CommandQueue);
 return IsEqualGUID(iid,&IID_ID3D12CommandList)||IsEqualGUID(iid,&IID_ID3D12GraphicsCommandList)||IsEqualGUID(iid,&IID_ID3D12GraphicsCommandList1)||IsEqualGUID(iid,&IID_ID3D12GraphicsCommandList2)||IsEqualGUID(iid,&IID_ID3D12GraphicsCommandList3)||IsEqualGUID(iid,&IID_ID3D12GraphicsCommandList4)||IsEqualGUID(iid,&IID_ID3D12GraphicsCommandList5)||IsEqualGUID(iid,&IID_ID3D12GraphicsCommandList6)||IsEqualGUID(iid,&IID_ID3D12GraphicsCommandList7);
}
static HRESULT STDMETHODCALLTYPE scoped_query(struct scoped_com*p,REFIID iid,void**out){
 if(!out)return E_POINTER;*out=NULL;void*real=NULL;HRESULT hr=IUnknown_QueryInterface(p->real,iid,&real);
 if(FAILED(hr))return hr;
 if(scoped_iid(p->kind,iid)){IUnknown_Release((IUnknown*)real);scoped_addref(p);*out=p;}else *out=real;
 return hr;
}
static struct scoped_com*scoped_wrap(IUnknown*real,UINT kind,UINT scope,struct scoped_tables*tables){
 if(!real)return NULL;struct scoped_com*p=HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(*p));if(!p)return NULL;
 p->tables=tables;
 p->vtable=kind==SCOPED_DEVICE?tables->device:kind==SCOPED_LIST?tables->list:tables->queue;
 p->real=real;p->refs=2;p->kind=kind;p->scope=scope; /* caller + scope lifetime */
 AcquireSRWLockExclusive(&scoped_lock);
 if(kind==SCOPED_DEVICE){UINT count=0;for(struct scoped_com*v=scoped_objects;v;v=v->next)if(v->kind==SCOPED_DEVICE)count++;
  if(count>=16){ReleaseSRWLockExclusive(&scoped_lock);HeapFree(GetProcessHeap(),0,p);proxy_log("SCOPED capacity reached; using original context\n");return NULL;}}
 InterlockedIncrement(&tables->refs);p->next=scoped_objects;scoped_objects=p;ReleaseSRWLockExclusive(&scoped_lock);return p;
}
static HRESULT STDMETHODCALLTYPE scoped_get_device(struct scoped_com*p,REFIID iid,void**out){
 struct scoped_com*device=NULL;AcquireSRWLockShared(&scoped_lock);
 for(struct scoped_com*v=scoped_objects;v;v=v->next)if(v->kind==SCOPED_DEVICE&&v->scope==p->scope){device=v;scoped_addref(device);break;}
 ReleaseSRWLockShared(&scoped_lock);if(!device)return E_FAIL;HRESULT hr=scoped_query(device,iid,out);scoped_release(device);return hr;
}
static HRESULT STDMETHODCALLTYPE scoped_create_list(struct scoped_com*d,UINT node,D3D12_COMMAND_LIST_TYPE type,ID3D12CommandAllocator*a,ID3D12PipelineState*pso,REFIID iid,void**out){
 D3D12_COMMAND_LIST_TYPE requested=type;
 ID3D12Device*real=(void*)d->real;HRESULT hr=ID3D12Device_CreateCommandList(real,node,type,a,pso,iid,out);if(FAILED(hr))return hr;
 if(!scoped_iid(SCOPED_LIST,iid))return hr;
 struct scoped_com*p=scoped_wrap(*out,SCOPED_LIST,d->scope,d->tables);if(!p){IUnknown_Release((IUnknown*)*out);*out=NULL;return E_OUTOFMEMORY;}*out=p;proxy_log("SCOPED command-list created\n");
 (void)requested;return hr;
}
static HRESULT STDMETHODCALLTYPE scoped_create_list1(struct scoped_com*d,UINT node,D3D12_COMMAND_LIST_TYPE type,D3D12_COMMAND_LIST_FLAGS flags,REFIID iid,void**out){
 ID3D12Device4*real=(void*)d->real;HRESULT hr=ID3D12Device4_CreateCommandList1(real,node,type,flags,iid,out);if(FAILED(hr))return hr;
 if(!scoped_iid(SCOPED_LIST,iid))return hr;
 struct scoped_com*p=scoped_wrap(*out,SCOPED_LIST,d->scope,d->tables);if(!p){IUnknown_Release((IUnknown*)*out);*out=NULL;return E_OUTOFMEMORY;}*out=p;proxy_log("SCOPED command-list1 created\n");return hr;
}
static HRESULT STDMETHODCALLTYPE scoped_create_queue(struct scoped_com*d,const D3D12_COMMAND_QUEUE_DESC*desc,REFIID iid,void**out){
 HRESULT hr=ID3D12Device_CreateCommandQueue((ID3D12Device*)d->real,desc,iid,out);if(FAILED(hr)||!scoped_iid(SCOPED_QUEUE,iid))return hr;
 struct scoped_com*p=scoped_wrap(*out,SCOPED_QUEUE,d->scope,d->tables);if(!p){IUnknown_Release((IUnknown*)*out);*out=NULL;return E_OUTOFMEMORY;}*out=p;return hr;
}
static void STDMETHODCALLTYPE scoped_execute(struct scoped_com*q,UINT count,ID3D12CommandList*const*lists){
 if(!count){ID3D12CommandQueue_ExecuteCommandLists((ID3D12CommandQueue*)q->real,0,lists);return;}
 ID3D12CommandList*local[16];ID3D12CommandList**raw=count<=16?local:HeapAlloc(GetProcessHeap(),0,sizeof(*raw)*count);
 if(!raw){proxy_log("FAIL command-list array allocation\n");ExitProcess(13);}
 for(UINT i=0;i<count;i++)raw[i]=(void*)scoped_raw((IUnknown*)lists[i]);
 ID3D12CommandQueue_ExecuteCommandLists((ID3D12CommandQueue*)q->real,count,raw);if(raw!=local)HeapFree(GetProcessHeap(),0,raw);
}
static void STDMETHODCALLTYPE scoped_bundle(struct scoped_com*l,ID3D12GraphicsCommandList*b){ID3D12GraphicsCommandList_ExecuteBundle((ID3D12GraphicsCommandList*)l->real,(void*)scoped_raw((IUnknown*)b));}
static uint64_t scoped_hash(const void*data,SIZE_T size){const unsigned char*p=data;uint64_t h=0xcbf29ce484222325ULL;for(SIZE_T i=0;i<size;i++)h=h*0x100000001b3ULL^p[i];return h;}
static HRESULT STDMETHODCALLTYPE scoped_compute(struct scoped_com*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,REFIID iid,void**out){
 uint64_t h=scoped_hash(desc->CS.pShaderBytecode,desc->CS.BytecodeLength);HRESULT hr=ID3D12Device_CreateComputePipelineState((ID3D12Device*)d->real,desc,iid,out);
 char line[180];snprintf(line,sizeof(line),"SCOPED PSO %016llx result=%lx\n",(unsigned long long)h,(long)hr);proxy_log(line);return hr;
}
static HRESULT STDMETHODCALLTYPE scoped_placed(struct scoped_com*d,ID3D12Heap*heap,UINT64 offset,const D3D12_RESOURCE_DESC*desc,D3D12_RESOURCE_STATES state,const D3D12_CLEAR_VALUE*clear,REFIID iid,void**out){
 if(desc->Dimension==D3D12_RESOURCE_DIMENSION_BUFFER&&desc->Flags==0&&state==D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE){char line[160];snprintf(line,sizeof(line),"SCOPED buffer bytes=%llu\n",(unsigned long long)desc->Width);proxy_log(line);}
 return ID3D12Device_CreatePlacedResource((ID3D12Device*)d->real,heap,offset,desc,state,clear,iid,out);
}
static void scale_source_written(ID3D12Resource*);
/* Only private SDK history copies qualify. Any transition back to a writable
 * state revokes reuse before the original operation is forwarded. */
static void STDMETHODCALLTYPE scale_history_barrier(struct scoped_com*l,UINT n,const D3D12_RESOURCE_BARRIER*b){
 for(UINT i=0;i<n;i++){
  if(b[i].Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION&&
    (b[i].Transition.StateAfter&(D3D12_RESOURCE_STATE_UNORDERED_ACCESS|D3D12_RESOURCE_STATE_RENDER_TARGET|D3D12_RESOURCE_STATE_COPY_DEST|D3D12_RESOURCE_STATE_RESOLVE_DEST)))scale_source_written(b[i].Transition.pResource);
  if(b[i].Type==D3D12_RESOURCE_BARRIER_TYPE_ALIASING){scale_source_written(b[i].Aliasing.pResourceBefore);scale_source_written(b[i].Aliasing.pResourceAfter);}
 }
 ID3D12GraphicsCommandList_ResourceBarrier((ID3D12GraphicsCommandList*)l->real,n,b);
}
static BOOL CALLBACK scoped_initialize(PINIT_ONCE once,PVOID parameter,PVOID*context){
 (void)once;(void)parameter;(void)context;
 void**tables[]={scoped_device_vtable,scoped_list_vtable,scoped_queue_vtable};UINT counts[]={SCOPED_device_COUNT,SCOPED_list_COUNT,SCOPED_queue_COUNT};
 for(UINT t=0;t<3;t++){for(UINT i=0;i<counts[t];i++)tables[t][i]=scoped_forwarders[i];tables[t][0]=scoped_query;tables[t][1]=scoped_addref;tables[t][2]=scoped_release;}
 scoped_device_vtable[SCOPED_device_CreateCommandList]=scoped_create_list;scoped_device_vtable[SCOPED_device_CreateCommandList1]=scoped_create_list1;scoped_device_vtable[SCOPED_device_CreateCommandQueue]=scoped_create_queue;
 scoped_device_vtable[SCOPED_device_CreateComputePipelineState]=scoped_compute;scoped_device_vtable[SCOPED_device_CreatePlacedResource]=scoped_placed;
 scoped_list_vtable[SCOPED_list_GetDevice]=scoped_get_device;scoped_queue_vtable[SCOPED_queue_GetDevice]=scoped_get_device;
 scoped_queue_vtable[SCOPED_queue_ExecuteCommandLists]=scoped_execute;scoped_list_vtable[SCOPED_list_ExecuteBundle]=scoped_bundle;
 scoped_list_vtable[SCOPED_list_ResourceBarrier]=scale_history_barrier;
 return TRUE;
}
static ID3D12Device*scoped_begin(ID3D12Device*real){
 if(!InitOnceExecuteOnce(&scoped_once,scoped_initialize,NULL,NULL))return NULL;
 struct scoped_tables*t=HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(*t));if(!t)return NULL;
 memcpy(t->device,scoped_device_vtable,sizeof(t->device));memcpy(t->list,scoped_list_vtable,sizeof(t->list));memcpy(t->queue,scoped_queue_vtable,sizeof(t->queue));
 IUnknown_AddRef((IUnknown*)real);struct scoped_com*p=scoped_wrap((IUnknown*)real,SCOPED_DEVICE,(UINT)InterlockedIncrement(&scoped_sequence),t);
 if(!p){HeapFree(GetProcessHeap(),0,t);IUnknown_Release((IUnknown*)real);return NULL;}return (void*)p;
}
static void scoped_remember(xefg_swapchain_handle_t handle,ID3D12Device*device){
 AcquireSRWLockExclusive(&scoped_lock);UINT i;for(i=0;i<16;i++)if(!scoped_contexts[i].handle){scoped_contexts[i].handle=handle;scoped_contexts[i].device=(void*)device;scoped_contexts[i].scope=((struct scoped_com*)device)->scope;break;}ReleaseSRWLockExclusive(&scoped_lock);
 if(i==16)proxy_log("SCOPED context table full: this context is not tracked\n");
}
static ID3D12CommandQueue*scoped_application_queue(xefg_swapchain_handle_t handle,ID3D12CommandQueue*real){
 if(!handle)return NULL;  /* free slots hold NULL handles */
 UINT scope=0;struct scoped_tables*t=NULL;AcquireSRWLockShared(&scoped_lock);for(UINT i=0;i<16;i++)if(scoped_contexts[i].handle==handle){scope=scoped_contexts[i].scope;t=scoped_contexts[i].device->tables;}ReleaseSRWLockShared(&scoped_lock);if(!scope||!real)return NULL;
 IUnknown_AddRef((IUnknown*)real);struct scoped_com*p=scoped_wrap((IUnknown*)real,SCOPED_QUEUE,scope,t);if(!p){IUnknown_Release((IUnknown*)real);return NULL;}
 return(void*)p;
}
static void scoped_destroy(xefg_swapchain_handle_t handle){
 if(!handle)return;  /* a free slot's stale device must never be released */
 UINT scope=0;struct scoped_com*device=NULL,*retired=NULL;
 AcquireSRWLockExclusive(&scoped_lock);
 for(UINT i=0;i<16;i++)if(scoped_contexts[i].handle==handle){scope=scoped_contexts[i].scope;device=scoped_contexts[i].device;memset(&scoped_contexts[i],0,sizeof(scoped_contexts[i]));break;}
 struct scoped_com**link=&scoped_objects;while(*link){struct scoped_com*p=*link;if(scope&&p->scope==scope){*link=p->next;p->next=retired;retired=p;}else link=&p->next;}
 ReleaseSRWLockExclusive(&scoped_lock);
 if(device)scoped_release(device); /* adapter's retained context-device ref */
 while(retired){struct scoped_com*p=retired;retired=p->next;scoped_release(p);}
 proxy_log("SCOPED context released\n");
}
