/* SPDX-License-Identifier: MIT
 * Standalone XeFG workload. Timestamp/vtable technique adapted from BC250 FSR4's
 * MIT provider_probe.c. Uses Intel's public XeFG/XeLL headers and original DLLs. */
#define WIDL_C_INLINE_WRAPPERS
#define COBJMACROS
#define INITGUID
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <xefg_swapchain_d3d12.h>
#include <xefg_swapchain_debug.h>
/* XeLL public header uses its enum tag as a typedef in a C size check. */
typedef enum _xell_latency_marker_type_t _xell_latency_marker_type_t;
#include <xell_d3d12.h>
int _fltused;
/* Hooks the multi-frame build (XEFG_MFG_RESEARCH) calls from the core below: the add-on build defines these two as
 * no-ops (release/build_addon.py PROBE_PATCHES finds them by their exact text). */
static void mfg_note_queue(ID3D12CommandQueue*);
static void mfg_capture_dispatch(ID3D12GraphicsCommandList*,uint64_t);
static void mfg_trace_hash(HMODULE);
static void mfg_install_capture(ID3D12Device*,ID3D12GraphicsCommandList*);
static void mfg_capture_report(void);
static HANDLE output;
/* The output folder of save(): only the standalone probe and the diagnostic game builds named here write files. */
static char directory[1024];
static char patchdir[1024];
static void logline(const char*s){DWORD n;WriteFile(output,s,(DWORD)strlen(s),&n,NULL);}
static void check(long r,const char*s){if(r<0){char b[512];snprintf(b,sizeof(b),"FAIL %s: %lx\n",s,r);logline(b);ExitProcess(10);}}
#define HR(x) check((x),#x)
#define LOAD(lib,n) __typeof__(&n) p_##n=(void*)GetProcAddress(lib,#n);if(!p_##n)ExitProcess(2)
static void logger(const char*s,xefg_swapchain_logging_level_t l,void*u){(void)l;(void)u;logline(s);logline("\n");}
static void save(const char*name,const void*data,size_t size){char path[1200];snprintf(path,sizeof(path),"%s\\%s",directory,name);HANDLE f=CreateFileA(path,GENERIC_WRITE,0,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);if(f==INVALID_HANDLE_VALUE){if(GetLastError()==ERROR_FILE_EXISTS)return;ExitProcess(11);}DWORD n;WriteFile(f,data,(DWORD)size,&n,NULL);CloseHandle(f);}
static ID3D12Resource* buffer(ID3D12Device*d,UINT64 size,D3D12_HEAP_TYPE heap){
 D3D12_HEAP_PROPERTIES h={.Type=heap,.CreationNodeMask=1,.VisibleNodeMask=1};D3D12_RESOURCE_DESC r={.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER,.Width=size,.Height=1,.DepthOrArraySize=1,.MipLevels=1,.SampleDesc={1,0},.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR};ID3D12Resource*b;
 HR(ID3D12Device_CreateCommittedResource(d,&h,0,&r,heap==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_COPY_DEST,NULL,&IID_ID3D12Resource,(void**)&b));return b;
}
static void transition(ID3D12GraphicsCommandList*l,ID3D12Resource*r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after){D3D12_RESOURCE_BARRIER b={.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION,.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after}};ID3D12GraphicsCommandList_ResourceBarrier(l,1,&b);}
static void replace(void*slot,void*p){DWORD old,tmp;HR(VirtualProtect(slot,sizeof(p),PAGE_READWRITE,&old)?0:-1);memcpy(slot,&p,sizeof(p));VirtualProtect(slot,sizeof(p),old,&tmp);}
static uint64_t hash(const void*p,size_t n){uint64_t h=0xcbf29ce484222325ULL;const unsigned char*b=p;for(size_t i=0;i<n;i++)h=h*0x100000001b3ULL^b[i];return h;}
/* Capacities of the pipeline and command-list tables. Intel's runtime without the BC-250 path (BC250_XEFG_DISABLE, other
 * GPUs) creates a fresh set of its ~43 pipelines at every multiplier change, where the add-on's pool reuses them, so a
 * factor-switching probe of that path is built with larger tables. A full table ends the process (exit 13) with a FAIL line. */
#ifndef XEFG_PROBE_PSOS
#define XEFG_PROBE_PSOS 256
#endif
#ifndef XEFG_PROBE_BINDINGS
#define XEFG_PROBE_BINDINGS 128
#endif
#define PROBE_TABLE_FULL(what) ExitProcess(13)
static struct{void*p;uint64_t hash;} psos[XEFG_PROBE_PSOS];static LONG npsos;
static struct{uint64_t shader;UINT factor;int x,y;} split_z[32];static UINT split_count;
static UINT scale_log; /* diagnostic: XEFG_SCALE_LOG=1 logs every scaled dispatch */
static void load_dispatch_scale(const char*path,int xyz){
 {char v[8];scale_log=GetEnvironmentVariableA("XEFG_SCALE_LOG",v,sizeof(v))&&v[0]=='1';}
 FILE*f=fopen(path,"r");if(!f||split_count)ExitProcess(40);char row[256];
 while(fgets(row,sizeof(row),f)){
  if(strspn(row," \t\r\n")==strlen(row))continue;
  unsigned long long shader;int x=1,y=1;unsigned z;char extra;
  int fields=xyz?sscanf(row,"%16llx %d %d %u %c",&shader,&x,&y,&z,&extra):sscanf(row,"%16llx %u %c",&shader,&z,&extra);
  if(fields!=(xyz?4:2)||split_count==32||!shader||!x||!y||!z||x>16||y>16||x< -16||y< -16||z>16)ExitProcess(40);
  for(UINT i=0;i<split_count;i++)if(split_z[i].shader==shader)ExitProcess(40);
  split_z[split_count].shader=shader;split_z[split_count].x=x;split_z[split_count].y=y;split_z[split_count++].factor=z;
 }
 if(ferror(f)||!split_count)ExitProcess(40);fclose(f);
}
static HRESULT (STDMETHODCALLTYPE *queue_original)(ID3D12Device*,const D3D12_COMMAND_QUEUE_DESC*,REFIID,void**);
static HRESULT STDMETHODCALLTYPE queue_hook(ID3D12Device*d,const D3D12_COMMAND_QUEUE_DESC*desc,REFIID iid,void**out){
 HRESULT r=queue_original(d,desc,iid,out);char line[256];snprintf(line,sizeof(line),"QUEUE type=%u priority=%d flags=%u node=%u result=%lx pointer=%p\n",desc->Type,desc->Priority,desc->Flags,desc->NodeMask,(long)r,SUCCEEDED(r)?*out:NULL);logline(line);
 if(SUCCEEDED(r))mfg_note_queue(*out);
 return r;
}
static HRESULT (STDMETHODCALLTYPE *compute_original)(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,REFIID,void**);
#include "warp_split.h"
static void model_root_check(ID3D12RootSignature*);
static UINT model_shader_bytes(uint64_t);
static UINT env_uint(const char*,UINT);
/* Intel-free add-on (release/INTEL-FREE.md): a replacement named <hash>.dxil loads only when the add-on's profile manifest
 * lists it, so files an earlier build left in the profile folder never run; every other shader stays Intel's original. */
static int profile_lists_replacement(uint64_t);
static void flow_capture_pso(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,uint64_t,ID3D12PipelineState*);
static int flow_dispatch_pso(ID3D12GraphicsCommandList*,uint64_t,UINT,UINT,UINT);
static void frame_capture_pso(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,uint64_t,ID3D12PipelineState*);
static int frame_dispatch_pso(ID3D12GraphicsCommandList*,uint64_t,UINT,UINT,UINT);
static void frame_finish_dispatch(ID3D12GraphicsCommandList*,uint64_t);
static HRESULT STDMETHODCALLTYPE compute_hook(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,REFIID iid,void**out){
 uint64_t h=hash(desc->CS.pShaderBytecode,desc->CS.BytecodeLength);D3D12_COMPUTE_PIPELINE_STATE_DESC copy=*desc;void*replacement=NULL;char path[1200],line[256];
 if(model_shader_bytes(h))model_root_check(desc->pRootSignature);
 if(*patchdir
    &&profile_lists_replacement(h)
    ){snprintf(path,sizeof(path),"%s\\%016llx.dxil",patchdir,(unsigned long long)h);HANDLE f=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);if(f!=INVALID_HANDLE_VALUE){DWORD size=GetFileSize(f,NULL),n;replacement=malloc(size);if(!ReadFile(f,replacement,size,&n,NULL)||n!=size)ExitProcess(12);CloseHandle(f);copy.CS.pShaderBytecode=replacement;copy.CS.BytecodeLength=size;copy.CachedPSO=(D3D12_CACHED_PIPELINE_STATE){0};snprintf(line,sizeof(line),"REPLACE %016llx %lu\n",(unsigned long long)h,size);logline(line);}}
 HRESULT hr=compute_original(d,&copy,iid,out);free(replacement);
 if(SUCCEEDED(hr))flow_capture_pso(d,desc,h,*out);
 if(SUCCEEDED(hr))frame_capture_pso(d,desc,h,*out);
 if(SUCCEEDED(hr)){LONG i=InterlockedIncrement(&npsos)-1;if(i>=XEFG_PROBE_PSOS){PROBE_TABLE_FULL("pipeline table full");}psos[i].p=*out;psos[i].hash=h;warp_split_capture(d,desc,h,*out);snprintf(line,sizeof(line),"PSO %p %016llx\n",*out,(unsigned long long)h);logline(line);}return hr;
}
#define MAXPASSES 16000
static ID3D12QueryHeap*queries;static ID3D12Resource*times;static LONG count;static UINT frame;static int tracing;static UINT fsr_recording;
static struct{ID3D12GraphicsCommandList*l;ID3D12PipelineState*p;} bindings[XEFG_PROBE_BINDINGS];static UINT nbinding;
static struct{UINT frame,x,y,z,fsr;uint64_t shader;} records[MAXPASSES];
static struct{ID3D12GraphicsCommandList*list;LONG index;int open;} spans[128];static UINT nspans;
static SRWLOCK span_lock=SRWLOCK_INIT;
static HRESULT(STDMETHODCALLTYPE *close_original)(ID3D12GraphicsCommandList*);
static HRESULT STDMETHODCALLTYPE close_hook(ID3D12GraphicsCommandList*l){
 AcquireSRWLockExclusive(&span_lock);
 for(UINT s=0;s<nspans;s++)if(spans[s].list==l&&spans[s].open){LONG i=spans[s].index;ID3D12GraphicsCommandList_EndQuery(l,queries,D3D12_QUERY_TYPE_TIMESTAMP,i*2+1);ID3D12GraphicsCommandList_ResolveQueryData(l,queries,D3D12_QUERY_TYPE_TIMESTAMP,i*2,2,times,(UINT64)i*16);spans[s].open=0;}
 ReleaseSRWLockExclusive(&span_lock);return close_original(l);
}
static void(STDMETHODCALLTYPE *set_original)(ID3D12GraphicsCommandList*,ID3D12PipelineState*);
static void STDMETHODCALLTYPE set_hook(ID3D12GraphicsCommandList*l,ID3D12PipelineState*p){UINT i;for(i=0;i<nbinding;i++)if(bindings[i].l==l)break;if(i==nbinding){if(i==XEFG_PROBE_BINDINGS){PROBE_TABLE_FULL("command-list binding table full");}bindings[i].l=l;nbinding++;}bindings[i].p=p;set_original(l,p);}
static void(STDMETHODCALLTYPE *dispatch_original)(ID3D12GraphicsCommandList*,UINT,UINT,UINT);
static int graph_dispatch(ID3D12GraphicsCommandList*,uint64_t,UINT,UINT,UINT);
static void dispatch_selected(ID3D12GraphicsCommandList*l,uint64_t shader,UINT x,UINT y,UINT z){
 if(flow_dispatch_pso(l,shader,x,y,z))return;
 if(frame_dispatch_pso(l,shader,x,y,z))return;
 if(warp_split_requested&&shader==0x3a7d9dfa831ba4f3ULL){
  ID3D12PipelineState*original=NULL;for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)original=bindings[b].p;
  if(!original||!x||!y||z!=1)ExitProcess(61);
  for(UINT i=0;i<warp_split_count;i++)if(warp_split_psos[i].original==original){
   set_original(l,warp_split_psos[i].motion);dispatch_original(l,x,y,z);
   D3D12_RESOURCE_BARRIER barrier={.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV,.UAV={NULL}};ID3D12GraphicsCommandList_ResourceBarrier(l,1,&barrier);
   set_original(l,warp_split_psos[i].rest);dispatch_original(l,x,y,z);set_original(l,original);warp_split_calls++;return;
  }
  ExitProcess(61);
 }
 if(!graph_dispatch(l,shader,x,y,z))dispatch_original(l,x,y,z);
 mfg_capture_dispatch(l,shader);
 frame_finish_dispatch(l,shader);
}
static void capture_dispatch(ID3D12GraphicsCommandList*,uint64_t);static void tap_dispatch(ID3D12GraphicsCommandList*,uint64_t);static void const_override(ID3D12GraphicsCommandList*,uint64_t);
static void model_dispatch_check(ID3D12GraphicsCommandList*,uint64_t);
/* The multi-frame proxy beside another module hooking Intel's XeFG runtime (src/game/mfg_proxy_coexist.h). */
static int proxy_census_soft(const char*);static int proxy_aside_active(void);static int proxy_dispatch_unready(uint64_t);
static void proxy_aside_dispatch(ID3D12GraphicsCommandList*,UINT,UINT,UINT);
static void flow_cap_dispatch(ID3D12GraphicsCommandList*,uint64_t,UINT*,UINT*,UINT*);
/* XeFG's final output pass, recorded once for every generated frame on every route and factor (the pacing signal). */
static LONG64 frame_outputs_recorded;
static void STDMETHODCALLTYPE dispatch_hook(ID3D12GraphicsCommandList*l,UINT x,UINT y,UINT z){
 uint64_t shader=0;
 for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)for(LONG s=0;s<npsos;s++)if(psos[s].p==bindings[b].p)shader=psos[s].hash;
 if(shader==0x977942d5d9337711ULL||shader==0x7da098e8e69a54f8ULL)InterlockedIncrement64(&frame_outputs_recorded);
 flow_cap_dispatch(l,shader,&x,&y,&z);
 /* Stepped aside (or stepping aside now): this dispatch as Intel recorded it. */
 if(proxy_dispatch_unready(shader)||proxy_aside_active()){proxy_aside_dispatch(l,x,y,z);return;}
 model_dispatch_check(l,shader);
 if(proxy_aside_active()){proxy_aside_dispatch(l,x,y,z);return;}
 for(UINT s=0;s<split_count;s++)if(split_z[s].shader==shader){
  int sx=split_z[s].x,sy=split_z[s].y;
  // Negative X/Y factors mean ceiling division for larger shader workgroups.
  // Bounds precede arithmetic; positive factors preserve the earlier format.
  if(z!=1||x>65535||y>65535||(sx>0&&x>65535/(UINT)sx)||(sy>0&&y>65535/(UINT)sy))ExitProcess(40);
  UINT ox=x,oy=y;
  x=sx>0?x*(UINT)sx:(x+(UINT)(-sx)-1)/(UINT)(-sx);
  y=sy>0?y*(UINT)sy:(y+(UINT)(-sy)-1)/(UINT)(-sy);z=split_z[s].factor;
  if(scale_log){char line[160];snprintf(line,sizeof(line),"SCALE_DISPATCH %016llx %u %u 1 -> %u %u %u\n",(unsigned long long)shader,ox,oy,x,y,z);logline(line);}
 }
 if(tracing==2){
  AcquireSRWLockExclusive(&span_lock);UINT s;for(s=0;s<nspans;s++)if(spans[s].list==l)break;
  if(s==nspans){if(nspans==128)ExitProcess(14);spans[nspans++].list=l;}
  if(!spans[s].open){LONG i=InterlockedIncrement(&count)-1;if(i>=MAXPASSES)ExitProcess(14);spans[s].index=i;spans[s].open=1;records[i].frame=frame;records[i].shader=UINT64_MAX;ID3D12GraphicsCommandList_EndQuery(l,queries,D3D12_QUERY_TYPE_TIMESTAMP,i*2);}
  records[spans[s].index].x++;ReleaseSRWLockExclusive(&span_lock);dispatch_selected(l,shader,x,y,z);return;
 }
 if(!tracing){dispatch_selected(l,shader,x,y,z);return;}LONG i=InterlockedIncrement(&count)-1;if(i>=MAXPASSES)ExitProcess(14);
 records[i].frame=frame;records[i].x=x;records[i].y=y;records[i].z=z;
 records[i].shader=shader;records[i].fsr=fsr_recording;
 capture_dispatch(l,records[i].shader);
 const_override(l,records[i].shader);ID3D12GraphicsCommandList_EndQuery(l,queries,D3D12_QUERY_TYPE_TIMESTAMP,i*2);dispatch_selected(l,shader,x,y,z);ID3D12GraphicsCommandList_EndQuery(l,queries,D3D12_QUERY_TYPE_TIMESTAMP,i*2+1);tap_dispatch(l,records[i].shader);
 ID3D12GraphicsCommandList_ResolveQueryData(l,queries,D3D12_QUERY_TYPE_TIMESTAMP,i*2,2,times,(UINT64)i*16);
}
struct texture{ID3D12Resource*r,*upload;D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp;UINT64 size;};
static struct texture texture(ID3D12Device*d,UINT w,UINT h,DXGI_FORMAT fmt){struct texture t={0};D3D12_HEAP_PROPERTIES hp={.Type=D3D12_HEAP_TYPE_DEFAULT,.CreationNodeMask=1,.VisibleNodeMask=1};D3D12_RESOURCE_DESC rd={.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D,.Width=w,.Height=h,.DepthOrArraySize=1,.MipLevels=1,.Format=fmt,.SampleDesc={1,0}};HR(ID3D12Device_CreateCommittedResource(d,&hp,0,&rd,D3D12_RESOURCE_STATE_COPY_DEST,NULL,&IID_ID3D12Resource,(void**)&t.r));ID3D12Device_GetCopyableFootprints(d,&rd,0,1,0,&t.fp,NULL,NULL,&t.size);t.upload=buffer(d,t.size,D3D12_HEAP_TYPE_UPLOAD);return t;}
static void upload(ID3D12GraphicsCommandList*l,struct texture*t,ID3D12Resource*dest){D3D12_TEXTURE_COPY_LOCATION src={.pResource=t->upload,.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT,.PlacedFootprint=t->fp},dst={.pResource=dest,.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};ID3D12GraphicsCommandList_CopyTextureRegion(l,&dst,0,0,0,&src,NULL);}
static UINT env_uint(const char*k,UINT v){char b[32];if(GetEnvironmentVariableA(k,b,sizeof(b)))v=strtoul(b,NULL,10);return v;}
#include "capture_off.h"  /* game builds never install the standalone probe's capture hooks */
#include "model_owner.h"
#include "winograd_graph.h"
#include "flow_cap.h"
#include "mfg_heap_lifetime.h"
/* Game builds compile the core above: they slice this file at the next line (release/build_addon.py PROBE_SPLIT). Only
 * the standalone probe, which is not part of the public tree, reads on. */
#include "scene_motion.h"
