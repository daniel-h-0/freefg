/* SPDX-License-Identifier: MIT
 * Isolated, fail-closed proof: only 2560x1440 -> 1920x1080 flow geometry.
 * Retain SDK allocations/barriers/descriptors and all depth/MV inputs.
 * No extra buffers, queue, asynchronous lifetime, or swapchain-size changes.
 */
#include "flow_cap_contract.h"
#define FLOW_ROOTS 9
#define FLOW_END 76
static void frame_root_changed(ID3D12GraphicsCommandList*);
static void frame_reset_list(ID3D12GraphicsCommandList*);
static void install_frame_cap(ID3D12Device*,ID3D12GraphicsCommandList*);
static void frame_prepare_dispatch(ID3D12GraphicsCommandList*,uint64_t,UINT*,UINT*,UINT*,UINT*);
/* Filter variants replace scene-color resampling only. */
static void*frame_color_blob(const char*name,UINT*size){
 return graph_blob(name,size);
}
static int scale_dispatch(ID3D12GraphicsCommandList*,uint64_t,UINT,UINT,UINT);
static void scale_release(void);
static UINT flow_cap_enabled;
static struct{ID3D12PipelineState*original,*capped;} flow_psos[16];static UINT flow_pso_count;static UINT64 flow_frames;
static struct {ID3D12GraphicsCommandList*l;
 UINT scaled[FLOW_ROOTS][64];
 UINT values[FLOW_ROOTS][64];UINT64 mask[FLOW_ROOTS];UINT step,active;ID3D12RootSignature*root;
} flow_lists[128];
static UINT flow_list_count;
static SRWLOCK flow_lock=SRWLOCK_INIT;
static HRESULT(STDMETHODCALLTYPE*flow_reset_original)(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*);
static void(STDMETHODCALLTYPE*flow_constant_original)(ID3D12GraphicsCommandList*,UINT,UINT,UINT);
static void(STDMETHODCALLTYPE*flow_root_original)(ID3D12GraphicsCommandList*,ID3D12RootSignature*);
static void(STDMETHODCALLTYPE*flow_constants_original)(ID3D12GraphicsCommandList*,UINT,UINT,const void*,UINT);
static UINT flow_slot(ID3D12GraphicsCommandList*l){
 for(UINT i=0;i<flow_list_count;i++)if(flow_lists[i].l==l)return i;
 if(flow_list_count==128)model_fail("flow list capacity");UINT i=flow_list_count++;flow_lists[i].l=l;return i;
}
static void STDMETHODCALLTYPE flow_constants_hook(ID3D12GraphicsCommandList*l,UINT index,UINT n,const void*v,UINT offset){
 AcquireSRWLockExclusive(&flow_lock);
 if(index<FLOW_ROOTS&&offset<=64&&n<=64-offset){UINT i=flow_slot(l);memcpy(flow_lists[i].values[index]+offset,v,n*4);
 memcpy(flow_lists[i].scaled[index]+offset,v,n*4);
 for(UINT k=offset;k<offset+n;k++)flow_lists[i].mask[index]|=1ULL<<k;
 }
 ReleaseSRWLockExclusive(&flow_lock);
 flow_constants_original(l,index,n,v,offset);
}
static void STDMETHODCALLTYPE flow_constant_hook(ID3D12GraphicsCommandList*l,UINT index,UINT value,UINT offset){
 AcquireSRWLockExclusive(&flow_lock);if(index<FLOW_ROOTS&&offset<64){UINT i=flow_slot(l);flow_lists[i].values[index][offset]=value;
 flow_lists[i].scaled[index][offset]=value;
flow_lists[i].mask[index]|=1ULL<<offset;}ReleaseSRWLockExclusive(&flow_lock);
 flow_constant_original(l,index,value,offset);
}
static HRESULT STDMETHODCALLTYPE flow_reset_hook(ID3D12GraphicsCommandList*l,ID3D12CommandAllocator*a,ID3D12PipelineState*p){
 HRESULT hr=flow_reset_original(l,a,p);if(SUCCEEDED(hr)){AcquireSRWLockExclusive(&flow_lock);UINT i=flow_slot(l);memset(flow_lists[i].mask,0,sizeof(flow_lists[i].mask));flow_lists[i].root=NULL;flow_lists[i].active=0;flow_lists[i].step=FLOW_END;
 frame_reset_list(l);
 scale_reset_list(l);
 ReleaseSRWLockExclusive(&flow_lock);}return hr;
}
static void STDMETHODCALLTYPE flow_root_hook(ID3D12GraphicsCommandList*l,ID3D12RootSignature*r){
 AcquireSRWLockExclusive(&flow_lock);UINT i=flow_slot(l);if(flow_lists[i].root!=r){memset(flow_lists[i].mask,0,sizeof(flow_lists[i].mask));flow_lists[i].root=r;
 frame_root_changed(l);
 }ReleaseSRWLockExclusive(&flow_lock);flow_root_original(l,r);
}
static void flow_capture_pso(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,uint64_t shader,ID3D12PipelineState*original){
 if(env_uint("XEFG_FLOW_CAP",0)&&shader==0xbc7a0d422d51c159ULL)scale_invalidate();
 return; /* Keep Intel's original preprocessing PSO. */
 if(shader!=0xbc7a0d422d51c159ULL||!env_uint("XEFG_FLOW_CAP",0))return;
 if(flow_pso_count==16)model_fail("flow PSO capacity");
 UINT size;void*bytes=frame_color_blob("flow-preprocess.dxil",&size);D3D12_COMPUTE_PIPELINE_STATE_DESC copy=*desc;
 copy.CS.pShaderBytecode=bytes;copy.CS.BytecodeLength=size;copy.CachedPSO=(D3D12_CACHED_PIPELINE_STATE){0};
 ID3D12PipelineState*p;HR(compute_original(d,&copy,&IID_ID3D12PipelineState,(void**)&p));free(bytes);
 flow_psos[flow_pso_count].original=original;flow_psos[flow_pso_count++].capped=p;
}
static int flow_dispatch_pso(ID3D12GraphicsCommandList*l,uint64_t shader,UINT x,UINT y,UINT z){
 return shader==0xbc7a0d422d51c159ULL?scale_dispatch(l,shader,x,y,z):0;
 if(!flow_cap_enabled||shader!=0xbc7a0d422d51c159ULL)return 0;
 AcquireSRWLockExclusive(&flow_lock);UINT active=flow_lists[flow_slot(l)].active;ReleaseSRWLockExclusive(&flow_lock);if(!active)return 0;
 ID3D12PipelineState*original=NULL;for(UINT i=0;i<nbinding;i++)if(bindings[i].l==l)original=bindings[i].p;
 for(UINT i=0;i<flow_pso_count;i++)if(flow_psos[i].original==original){set_original(l,flow_psos[i].capped);dispatch_original(l,x,y,z);set_original(l,original);return 1;}
 model_fail("missing flow preprocessing PSO");return 0;
}
static void install_flow_cap(ID3D12GraphicsCommandList*l,UINT w,UINT h){
 UINT requested=env_uint("XEFG_FLOW_CAP",0);if(requested>1)model_fail("flow flag");
 if(!requested)return;
 (void)w;(void)h;
 if(!*patchdir)model_fail("flow requires paired profile");
 flow_reset_original=l->lpVtbl->Reset;replace((void*)&l->lpVtbl->Reset,flow_reset_hook);
 flow_constant_original=l->lpVtbl->SetComputeRoot32BitConstant;replace((void*)&l->lpVtbl->SetComputeRoot32BitConstant,flow_constant_hook);
 flow_root_original=l->lpVtbl->SetComputeRootSignature;replace((void*)&l->lpVtbl->SetComputeRootSignature,flow_root_hook);
 flow_cap_enabled=1;
 flow_constants_original=l->lpVtbl->SetComputeRoot32BitConstants;replace((void*)&l->lpVtbl->SetComputeRoot32BitConstants,flow_constants_hook);
 install_frame_cap(graph_device,l);
 logline("FLOW_CAP armed; generated-frame dimensions follow configured percentage or limit\n");
}
#include "mfg_frame_geometry.h"
static void flow_cap_dispatch(ID3D12GraphicsCommandList*l,uint64_t shader,UINT*x,UINT*y,UINT*z){
 if(!flow_cap_enabled||fsr_recording)return;
 AcquireSRWLockExclusive(&flow_lock);
 if(mfg_cap_dispatch_locked(l,shader,x,y,z)){ReleaseSRWLockExclusive(&flow_lock);return;}
 UINT i=flow_slot(l);UINT flow_step=flow_lists[i].step;
 if(shader==0xbc7a0d422d51c159ULL){
  if(flow_lists[i].active&&flow_step!=FLOW_END)model_fail("incomplete capped flow graph");
  UINT*w=flow_lists[i].values[3];
  if((flow_lists[i].mask[3]&1023)!=1023)model_fail("incomplete preprocessing constants");
  if(w[2]<=1920&&w[3]<=1080){flow_lists[i].active=0;flow_lists[i].step=FLOW_END;ReleaseSRWLockExclusive(&flow_lock);return;}
  if(w[2]!=2560||w[3]!=1440)model_fail("unsupported high-resolution flow prototype");
  flow_lists[i].active=1;flow_step=0;
 }
 if(!flow_lists[i].active){ReleaseSRWLockExclusive(&flow_lock);return;}
 if(flow_step<23&&shader==flow_rows[flow_step].shader){
  UINT index=flow_rows[flow_step].index,n=flow_rows[flow_step].n,*raw=flow_lists[i].values[index];
  if((flow_lists[i].mask[index]&((1ULL<<n)-1))!=((1ULL<<n)-1))model_fail("incomplete flow constants");
  /* Every dimension, pitch, layer, and padding value must match the census. */
  if(memcmp(raw,flow_rows[flow_step].old,n*4))model_fail("flow source contract changed");
  flow_constants_original(l,index,n,flow_rows[flow_step].target,0);
  *x=flow_rows[flow_step].groups[0];*y=flow_rows[flow_step].groups[1];*z=flow_rows[flow_step].groups[2];
  if(++flow_step==23)flow_frames++;
 }
 else{frame_prepare_dispatch(l,shader,x,y,z,&flow_step);}
 if(flow_step==38)flow_step=FLOW_END;
 flow_lists[i].step=flow_step;ReleaseSRWLockExclusive(&flow_lock);
}

#include "frame_cap.h"
