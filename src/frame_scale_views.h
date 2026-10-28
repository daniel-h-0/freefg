/* SPDX-License-Identifier: MIT
 * Owned colour-view resampling for the SDK's unchanged compute pipelines.
 * Descriptor snapshots are taken below model rewriting. Private heaps are
 * immutable once recorded; cached GPU resources survive until completion.
 * List reset/release drops recorded references. A queue fence protects submitted
 * references; only completed, unreferenced cache entries can be recycled.
 */
#define SCALE_VIEWS 64
#include "frame_scale_history.h"
static struct {SIZE_T cpu;struct scale_view v;} scale_descriptors[8192];
static UINT scale_descriptor_count,scale_enabled;
static struct {ID3D12RootSignature*r;UINT count[9],constants[9],mask,valid;} scale_roots[256];
static UINT scale_root_count;
static SRWLOCK scale_lock=SRWLOCK_INIT;
static __typeof__(model_srv_original) scale_srv_raw;
static __typeof__(model_uav_original) scale_uav_raw;
static __typeof__(model_cbv_original) scale_cbv_raw;
static __typeof__(model_simple_original) scale_simple_raw;
static __typeof__(model_descs_original) scale_descs_raw;
static ID3D12RootSignature*scale_filter_root;
static ID3D12PipelineState*scale_filter_pso;
static struct scale_image*scale_images;
static void scale_source_written(ID3D12Resource*r){
 if(!scale_enabled)return;
 AcquireSRWLockExclusive(&scale_lock);
 scale_history_written(scale_images,r);
 ReleaseSRWLockExclusive(&scale_lock);
}
static void scale_source_copied(ID3D12Resource*r){
 if(!scale_enabled)return;
 AcquireSRWLockExclusive(&scale_lock);
 scale_history_copied(scale_images,r);
 ReleaseSRWLockExclusive(&scale_lock);
}
struct scale_batch {
 ID3D12RootSignature*root;UINT w,h,n,count[9],offset[9];
 struct scale_view views[SCALE_VIEWS];
 struct scale_image*images[SCALE_VIEWS];
 UINT recorded;UINT64 fence;
 ID3D12DescriptorHeap*heap;UINT filters[SCALE_VIEWS];
 ID3D12Resource*direct_output;
 struct scale_batch*next;
};
static struct scale_batch*scale_batches;
static UINT scale_batch_count;
static ID3D12Fence*scale_fence;static UINT64 scale_serial;
struct scale_use {struct scale_batch*b;struct scale_use*next;};
static struct {ID3D12GraphicsCommandList*l;struct scale_use*uses;} scale_lists[128];
static UINT scale_list_count;
static UINT64 scale_dispatches,scale_resamples,scale_recycled;
static UINT64 scale_history_hits;
static UINT64 scale_graph;
static UINT scale_last_w,scale_last_h,scale_last_format;
static UINT scale_last_mode,scale_last_output_w,scale_last_output_h;static UINT64 scale_last_epoch;
static UINT64 scale_epoch=1,scale_qualified,scale_failed,scale_observing;
static UINT scale_key_w,scale_key_h,scale_key_format;
static struct scale_image*scale_image_get(const struct scale_view*v,UINT w,UINT h){
 for(struct scale_image*i=scale_images;i;i=i->next)if(i->w==w&&i->h==h&&!memcmp(&i->source,v,sizeof(*v))){i->refs++;return i;}
 struct scale_image*i=calloc(1,sizeof(*i));if(!i)model_fail("scaling image allocation");
 i->source=*v;i->w=w;i->h=h;i->refs=1;ID3D12Resource_AddRef(v->r);
 D3D12_HEAP_PROPERTIES hp={.Type=D3D12_HEAP_TYPE_DEFAULT};
 DXGI_FORMAT format=v->d.srv.Format==DXGI_FORMAT_R32G32B32A32_FLOAT?DXGI_FORMAT_R32G32B32A32_FLOAT:DXGI_FORMAT_R16G16B16A16_FLOAT;
 D3D12_RESOURCE_DESC rd={.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D,.Width=w,.Height=h,.DepthOrArraySize=1,.MipLevels=1,.Format=format,.SampleDesc={1,0},.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS};
 D3D12_FEATURE_DATA_FORMAT_SUPPORT support={.Format=format};
 if(SUCCEEDED(ID3D12Device_CheckFeatureSupport(frame_device,D3D12_FEATURE_FORMAT_SUPPORT,&support,sizeof(support)))&&(support.Support1&D3D12_FORMAT_SUPPORT1_RENDER_TARGET))rd.Flags|=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
 HR(model_committed_original(frame_device,&hp,0,&rd,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,NULL,&IID_ID3D12Resource,(void**)&i->low));
 i->next=scale_images;scale_images=i;return i;
}
static void scale_image_drop(struct scale_image*i){
 if(!i||--i->refs)return;
 struct scale_image**p=&scale_images;while(*p&&*p!=i)p=&(*p)->next;
 if(!*p)model_fail("scaling image ownership");*p=i->next;
 ID3D12Resource_Release(i->low);ID3D12Resource_Release(i->source.r);free(i);
}
static void scale_free_batch(struct scale_batch*b){
 if(b->direct_output)ID3D12Resource_Release(b->direct_output);
 for(UINT j=0;j<b->n;j++){
  scale_image_drop(b->images[j]);
  if(b->views[j].r)ID3D12Resource_Release(b->views[j].r);
  if(b->views[j].counter)ID3D12Resource_Release(b->views[j].counter);
 }
 ID3D12DescriptorHeap_Release(b->heap);free(b);scale_batch_count--;
}
static void scale_collect_locked(UINT all_unused){
 UINT64 done=scale_fence?ID3D12Fence_GetCompletedValue(scale_fence):0;
 if(done==UINT64_MAX)return; /* Device removal is not proof of completion. */
 struct scale_batch**p=&scale_batches;
 while(*p){struct scale_batch*b=*p;
  if(!b->recorded&&b->fence<=done&&(all_unused||scale_batch_count>=48)){
   *p=b->next;scale_free_batch(b);scale_recycled++;
  }else p=&b->next;
 }
}
static void scale_note_batch(ID3D12GraphicsCommandList*l,struct scale_batch*b){
 UINT i;for(i=0;i<scale_list_count;i++)if(scale_lists[i].l==l)break;
 if(i==scale_list_count){if(i==128)model_fail("scaling list capacity");scale_lists[i].l=l;scale_list_count++;}
 for(struct scale_use*u=scale_lists[i].uses;u;u=u->next)if(u->b==b)return;
 struct scale_use*u=malloc(sizeof(*u));if(!u)model_fail("scaling recorded reference allocation");
 u->b=b;u->next=scale_lists[i].uses;scale_lists[i].uses=u;b->recorded++;
}
static void scale_reset_list(ID3D12GraphicsCommandList*l){
 if(!scale_enabled)return;
 AcquireSRWLockExclusive(&scale_lock);
 scale_history_reset(scale_images,l);
 for(UINT i=0;i<scale_list_count;i++)if(scale_lists[i].l==l){
  struct scale_use*u=scale_lists[i].uses;
  while(u){struct scale_use*n=u->next;if(!u->b->recorded)model_fail("scaling recorded reference underflow");u->b->recorded--;free(u);u=n;}
  scale_lists[i]=scale_lists[--scale_list_count];memset(&scale_lists[scale_list_count],0,sizeof(*scale_lists));break;
 }
 scale_collect_locked(0);ReleaseSRWLockExclusive(&scale_lock);
}
static int scale_queue_execute(ID3D12CommandQueue*q,UINT n,ID3D12CommandList*const*lists,
 void(STDMETHODCALLTYPE*execute)(ID3D12CommandQueue*,UINT,ID3D12CommandList*const*)){
 if(!scale_enabled)return 0;
 AcquireSRWLockExclusive(&scale_lock);UINT used=0;
 for(UINT j=0;j<n;j++)for(UINT i=0;i<scale_list_count;i++)if(lists[j]==(ID3D12CommandList*)scale_lists[i].l&&scale_lists[i].uses)used=1;
 if(!used){ReleaseSRWLockExclusive(&scale_lock);return 0;}
 if(graph_queue&&q!=graph_queue)model_fail("scaling submitted on another queue");
 if(!scale_fence)HR(ID3D12Device_CreateFence(frame_device,0,0,&IID_ID3D12Fence,(void**)&scale_fence));
 if(scale_serial==UINT64_MAX-1)model_fail("scaling fence overflow");UINT64 serial=++scale_serial;
 execute(q,n,lists);HR(ID3D12CommandQueue_Signal(q,scale_fence,serial));
 for(UINT j=0;j<n;j++)scale_history_submitted(scale_images,lists[j]);
 for(UINT j=0;j<n;j++)for(UINT i=0;i<scale_list_count;i++)if(lists[j]==(ID3D12CommandList*)scale_lists[i].l)
  for(struct scale_use*u=scale_lists[i].uses;u;u=u->next)u->b->fence=serial;
 scale_collect_locked(0);ReleaseSRWLockExclusive(&scale_lock);return 1;
}
static void scale_purge_descriptors(SIZE_T cpu,SIZE_T bytes){
 if(!scale_enabled)return;
 AcquireSRWLockExclusive(&scale_lock);
 for(UINT i=0;i<scale_descriptor_count;)if(scale_descriptors[i].cpu>=cpu&&scale_descriptors[i].cpu-cpu<bytes){
  scale_descriptors[i]=scale_descriptors[--scale_descriptor_count];memset(&scale_descriptors[scale_descriptor_count],0,sizeof(*scale_descriptors));
 }else i++;
 ReleaseSRWLockExclusive(&scale_lock);
}
static struct {ID3D12PipelineState*original,*bounded;uint64_t shader;UINT64 calls;} scale_unet[256];static UINT scale_unet_count,scale_shader_failed;
static int scale_unet_shader(uint64_t h){
 return h==0x1a3b0782583fef19ULL||h==0xf030948d38e74671ULL||h==0xe83e868f8d5d2c0fULL||h==0x9e0080eee00255f2ULL||h==0x1f27b449fb99a587ULL||h==0x4bb52a635e6d221aULL||h==0xf2e2e13fea432d20ULL||h==0x5654aa3800432b13ULL||h==0xb3ddf030f661d487ULL||h==0xb3941ac8ff95efe7ULL||h==0x60edebbbd2f9fb69ULL;
}
static void scale_capture_unet(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,uint64_t shader,ID3D12PipelineState*original,const char*suffix){
 if(!scale_enabled||!scale_unet_shader(shader))return;
 for(UINT i=0;i<scale_unet_count;i++)if(scale_unet[i].original==original&&scale_unet[i].shader==shader)return;
 if(scale_unet_count==256){scale_shader_failed=1;return;}
 char name[80];snprintf(name,sizeof(name),"%016llx%s.scale.dxil",(unsigned long long)shader,suffix);
 UINT n;void*bytes=graph_blob(name,&n);D3D12_COMPUTE_PIPELINE_STATE_DESC copy=*desc;
 copy.CS=(D3D12_SHADER_BYTECODE){bytes,n};copy.CachedPSO=(D3D12_CACHED_PIPELINE_STATE){0};ID3D12PipelineState*bounded=NULL;
 HRESULT hr=compute_original(d,&copy,&IID_ID3D12PipelineState,(void**)&bounded);free(bytes);
 if(FAILED(hr)||!bounded){scale_shader_failed=1;logline("FREEFG_SCALE bounded convolution unavailable; retaining full output\n");return;}
 UINT i=scale_unet_count++;scale_unet[i].original=original;scale_unet[i].bounded=bounded;scale_unet[i].shader=shader;ID3D12PipelineState_AddRef(original);
}
static int scale_dispatch_unet(ID3D12GraphicsCommandList*l,uint64_t shader,UINT x,UINT y,UINT z){
 if(!scale_enabled||!scale_unet_shader(shader))return 0;
 UINT li=flow_slot(l);if(!flow_lists[li].active||!mfg_scale_actual[li])return 0;
 ID3D12PipelineState*original=NULL;for(UINT i=0;i<nbinding;i++)if(bindings[i].l==l)original=bindings[i].p;
 for(UINT i=0;i<scale_unet_count;i++)if(scale_unet[i].original==original&&scale_unet[i].shader==shader){
  set_original(l,scale_unet[i].bounded);dispatch_original(l,x,y,z);set_original(l,original);
  if(!scale_unet[i].calls){char line[140];snprintf(line,sizeof(line),"FREEFG_SCALE_UNET shader=%016llx dispatches=1\n",(unsigned long long)shader);logline(line);}
  scale_unet[i].calls++;return 1;
 }
 model_fail("scaled convolution pipeline missing");return 0;
}
static void scale_capture_root(ID3D12RootSignature*r,const D3D12_ROOT_SIGNATURE_DESC*d){
 if(!scale_enabled)return;
 AcquireSRWLockExclusive(&scale_lock);
 UINT i;for(i=0;i<scale_root_count;i++)if(scale_roots[i].r==r)break;
 if(i==scale_root_count){if(i==256)model_fail("scaling root capacity");scale_root_count++;scale_roots[i].r=r;ID3D12RootSignature_AddRef(r);}
 scale_roots[i].valid=d->NumParameters<=9;scale_roots[i].mask=0;
 memset(scale_roots[i].count,0,sizeof(scale_roots[i].count));memset(scale_roots[i].constants,0,sizeof(scale_roots[i].constants));
 for(UINT j=0;j<d->NumParameters&&j<9;j++){
  const D3D12_ROOT_PARAMETER*p=d->pParameters+j;
  if(p->ParameterType==D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS){scale_roots[i].constants[j]=p->Constants.Num32BitValues;continue;}
  if(p->ParameterType!=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE){scale_roots[i].valid=0;continue;}
  UINT end=0;const D3D12_ROOT_DESCRIPTOR_TABLE*t=&p->DescriptorTable;
  for(UINT k=0;k<t->NumDescriptorRanges;k++){
   const D3D12_DESCRIPTOR_RANGE*v=t->pDescriptorRanges+k;
   UINT start=v->OffsetInDescriptorsFromTableStart==D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND?end:v->OffsetInDescriptorsFromTableStart;
   if(v->RangeType==D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER||v->NumDescriptors>SCALE_VIEWS||start>SCALE_VIEWS-v->NumDescriptors){scale_roots[i].valid=0;break;}
   end=start+v->NumDescriptors;if(end>scale_roots[i].count[j])scale_roots[i].count[j]=end;
  }
  scale_roots[i].mask|=1u<<j;
 }
 ReleaseSRWLockExclusive(&scale_lock);
}
static struct scale_view scale_get(SIZE_T cpu){
 for(UINT i=0;i<scale_descriptor_count;i++)if(scale_descriptors[i].cpu==cpu)return scale_descriptors[i].v;
 return (struct scale_view){0};
}
static void scale_put(SIZE_T cpu,struct scale_view v){
 UINT i;for(i=0;i<scale_descriptor_count;i++)if(scale_descriptors[i].cpu==cpu)break;
 if(i==scale_descriptor_count){if(!v.kind)return;if(i==8192)model_fail("scaling descriptor capacity");scale_descriptors[i].cpu=cpu;scale_descriptor_count++;}
 scale_descriptors[i].v=v;
}
static void STDMETHODCALLTYPE scale_srv(ID3D12Device*d,ID3D12Resource*r,const D3D12_SHADER_RESOURCE_VIEW_DESC*v,D3D12_CPU_DESCRIPTOR_HANDLE h){
 scale_srv_raw(d,r,v,h);struct scale_view s={.kind=v?1:0,.r=r};if(v)s.d.srv=*v;
 AcquireSRWLockExclusive(&scale_lock);scale_put(h.ptr,s);ReleaseSRWLockExclusive(&scale_lock);
}
static void STDMETHODCALLTYPE scale_uav(ID3D12Device*d,ID3D12Resource*r,ID3D12Resource*c,const D3D12_UNORDERED_ACCESS_VIEW_DESC*v,D3D12_CPU_DESCRIPTOR_HANDLE h){
 scale_uav_raw(d,r,c,v,h);struct scale_view s={.kind=v?2:0,.r=r,.counter=c};if(v)s.d.uav=*v;
 AcquireSRWLockExclusive(&scale_lock);scale_put(h.ptr,s);ReleaseSRWLockExclusive(&scale_lock);
}
static void STDMETHODCALLTYPE scale_cbv(ID3D12Device*d,const D3D12_CONSTANT_BUFFER_VIEW_DESC*v,D3D12_CPU_DESCRIPTOR_HANDLE h){
 scale_cbv_raw(d,v,h);struct scale_view s={.kind=v?3:0};if(v)s.d.cbv=*v;
 AcquireSRWLockExclusive(&scale_lock);scale_put(h.ptr,s);ReleaseSRWLockExclusive(&scale_lock);
}
static void STDMETHODCALLTYPE scale_simple(ID3D12Device*d,UINT n,D3D12_CPU_DESCRIPTOR_HANDLE dst,D3D12_CPU_DESCRIPTOR_HANDLE src,D3D12_DESCRIPTOR_HEAP_TYPE type){
 scale_simple_raw(d,n,dst,src,type);if(type!=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV)return;
 UINT stride=ID3D12Device_GetDescriptorHandleIncrementSize(d,type);AcquireSRWLockExclusive(&scale_lock);
 for(UINT i=0;i<n;i++)scale_put(dst.ptr+(SIZE_T)i*stride,scale_get(src.ptr+(SIZE_T)i*stride));
 ReleaseSRWLockExclusive(&scale_lock);
}
static void STDMETHODCALLTYPE scale_descs(ID3D12Device*d,UINT nd,const D3D12_CPU_DESCRIPTOR_HANDLE*dst,const UINT*dn,UINT ns,const D3D12_CPU_DESCRIPTOR_HANDLE*src,const UINT*sn,D3D12_DESCRIPTOR_HEAP_TYPE type){
 scale_descs_raw(d,nd,dst,dn,ns,src,sn,type);if(type!=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV)return;
 UINT si=0,so=0,stride=ID3D12Device_GetDescriptorHandleIncrementSize(d,type);AcquireSRWLockExclusive(&scale_lock);
 for(UINT di=0;di<nd;di++)for(UINT off=0;off<(dn?dn[di]:1);off++){
  while(si<ns&&so==(sn?sn[si]:1)){si++;so=0;}if(si>=ns)model_fail("scaling descriptor range");
  scale_put(dst[di].ptr+(SIZE_T)off*stride,scale_get(src[si].ptr+(SIZE_T)so*stride));so++;
 }
 ReleaseSRWLockExclusive(&scale_lock);
}
static void scale_install(UINT enabled){
 scale_enabled=enabled;if(!enabled)return;
 scale_srv_raw=model_srv_original;model_srv_original=scale_srv;
 scale_uav_raw=model_uav_original;model_uav_original=scale_uav;
 scale_cbv_raw=model_cbv_original;model_cbv_original=scale_cbv;
 scale_simple_raw=model_simple_original;model_simple_original=scale_simple;
 scale_descs_raw=model_descs_original;model_descs_original=scale_descs;
}
static int scale_colour(const struct scale_view*v){

 if(v->kind!=1||!v->r||v->d.srv.ViewDimension!=D3D12_SRV_DIMENSION_TEXTURE2D||v->d.srv.Texture2D.MostDetailedMip||v->d.srv.Texture2D.PlaneSlice)return 0;
 switch(v->d.srv.Format){
 case DXGI_FORMAT_R8G8B8A8_UNORM:case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
 case DXGI_FORMAT_B8G8R8A8_UNORM:case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
 case DXGI_FORMAT_R10G10B10A2_UNORM:case DXGI_FORMAT_R16G16B16A16_FLOAT:case DXGI_FORMAT_R32G32B32A32_FLOAT:break;
 default:return 0;
 }
 if(!frame_format_supported(v->d.srv.Format==DXGI_FORMAT_R32G32B32A32_FLOAT?DXGI_FORMAT_R32G32B32A32_FLOAT:DXGI_FORMAT_R16G16B16A16_FLOAT))return 0;
 D3D12_RESOURCE_DESC d=ID3D12Resource_GetDesc(v->r);
 return d.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D&&d.Width==mfg_output_w&&d.Height==mfg_output_h&&d.DepthOrArraySize==1&&d.SampleDesc.Count==1;
}
static ID3D12RootSignature*scale_create_filter_root(UINT easu){
 D3D12_DESCRIPTOR_RANGE ranges[2]={
  {.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_SRV,.NumDescriptors=1},
  {.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_UAV,.NumDescriptors=1}};
 D3D12_ROOT_PARAMETER params[3]={0};
 for(UINT i=0;i<2;i++){params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[i].DescriptorTable=(D3D12_ROOT_DESCRIPTOR_TABLE){1,ranges+i};}
 params[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;params[2].Constants.Num32BitValues=16;
 D3D12_STATIC_SAMPLER_DESC sampler={.Filter=D3D12_FILTER_MIN_MAG_MIP_LINEAR,.AddressU=D3D12_TEXTURE_ADDRESS_MODE_CLAMP,
  .AddressV=D3D12_TEXTURE_ADDRESS_MODE_CLAMP,.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP,.MaxAnisotropy=16,
  .ComparisonFunc=D3D12_COMPARISON_FUNC_LESS_EQUAL,.BorderColor=D3D12_STATIC_BORDER_COLOR_OPAQUE_WHITE,.MaxLOD=D3D12_FLOAT32_MAX};
 D3D12_ROOT_SIGNATURE_DESC desc={.NumParameters=easu?3:2,.pParameters=params,.NumStaticSamplers=1,.pStaticSamplers=&sampler};
 HRESULT(WINAPI*serialize)(const D3D12_ROOT_SIGNATURE_DESC*,D3D_ROOT_SIGNATURE_VERSION,ID3DBlob**,ID3DBlob**)=(void*)GetProcAddress(GetModuleHandleA("d3d12.dll"),"D3D12SerializeRootSignature");
 if(!serialize)model_fail("scaling root serializer unavailable");ID3DBlob*blob=NULL;HR(serialize(&desc,D3D_ROOT_SIGNATURE_VERSION_1_0,&blob,NULL));
 ID3D12RootSignature*root=NULL;HR(model_create_root_original(frame_device,0,ID3D10Blob_GetBufferPointer(blob),ID3D10Blob_GetBufferSize(blob),&IID_ID3D12RootSignature,(void**)&root));
 ID3D10Blob_Release(blob);return root;
}
static void scale_filter_init(void){
 if(scale_filter_pso)return;
 UINT n;scale_filter_root=scale_create_filter_root(0);
 void*b=graph_blob(mfg_settings_applied.downscale==BC250_FG_AREA?"freefg-down-area.dxil":"freefg-down-bilinear.dxil",&n);
 D3D12_COMPUTE_PIPELINE_STATE_DESC d={.pRootSignature=scale_filter_root,.CS={b,n}};
 HR(compute_original(frame_device,&d,&IID_ID3D12PipelineState,(void**)&scale_filter_pso));free(b);
}
static void scale_low_transition(ID3D12GraphicsCommandList*l,ID3D12Resource*r,D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to){
 /* This is our reduction target, never an SDK history input. Bypass the
  * invalidation wrapper while holding scale_lock. */
 transition((ID3D12GraphicsCommandList*)scoped_raw((IUnknown*)l),r,from,to);
}
static int scale_snapshot_locked(ID3D12GraphicsCommandList*l,uint64_t shader,struct scale_view*views,UINT*out_n,UINT*offset,UINT*out_ri){
 ID3D12RootSignature*root=flow_lists[flow_slot(l)].root;UINT li=frame_list(l);
 UINT ri;for(ri=0;ri<scale_root_count;ri++)if(scale_roots[ri].r==root)break;
 if(ri==scale_root_count||!scale_roots[ri].valid)return 0;
 if((frame_lists[li].table_mask&scale_roots[ri].mask)!=scale_roots[ri].mask)return 0;
 static const UINT preprocess[9]={1,1,2},warp[9]={7,1,1,1,1,5},final[9]={5,3,1,1,1,1,1,1};
 const UINT*expected=shader==0xbc7a0d422d51c159ULL?preprocess:frame_final_shader(shader)?final:warp;
 UINT constant_index=shader==0xbc7a0d422d51c159ULL?3:frame_final_shader(shader)?8:6;
 UINT constant_count=constant_index==3?10:constant_index==8?18:51;
 if(memcmp(scale_roots[ri].count,expected,sizeof(preprocess))||scale_roots[ri].constants[constant_index]!=constant_count){
  char line[200];snprintf(line,sizeof(line),"FREEFG_SCALE root outside profile shader=%016llx tables=%u,%u,%u,%u,%u,%u,%u,%u,%u constants=%u\n",(unsigned long long)shader,scale_roots[ri].count[0],scale_roots[ri].count[1],scale_roots[ri].count[2],scale_roots[ri].count[3],scale_roots[ri].count[4],scale_roots[ri].count[5],scale_roots[ri].count[6],scale_roots[ri].count[7],scale_roots[ri].count[8],scale_roots[ri].constants[constant_index]);logline(line);return 0;
 }

 UINT n=0;
 for(UINT j=0;j<9;j++){
  UINT count=scale_roots[ri].count[j];offset[j]=n;if(!count)continue;
  if(count>SCALE_VIEWS-n)return 0;
  UINT64 gpu=frame_lists[li].table[j];SIZE_T cpu=0;UINT stride=0;
  for(UINT h=0;h<model_heap_count;h++){
   UINT64 base=model_heaps[h].gpu,bytes=(UINT64)model_heaps[h].count*model_heaps[h].stride;
   if(gpu>=base&&gpu-base<bytes){stride=model_heaps[h].stride;if((gpu-base)%stride||count>(bytes-(gpu-base))/stride)return 0;cpu=model_heaps[h].cpu+(SIZE_T)(gpu-base);break;}
  }
  if(!cpu)return 0;
  for(UINT k=0;k<count;k++){views[n]=scale_get(cpu+(SIZE_T)k*stride);if(!views[n].kind)return 0;n++;}
 }
 *out_n=n;*out_ri=ri;return 1;
}
static int scale_resources_valid(uint64_t shader,const struct scale_view*v,UINT n,const UINT*offset){
 if(!frame_format_supported(DXGI_FORMAT_R16G16B16A16_FLOAT))return 0;
 if(shader==0xbc7a0d422d51c159ULL){
  return n==4&&scale_colour(v)&&scale_colour(v+1)&&v[2].kind==2&&v[3].kind==2;
 }
 if(frame_warp_shader(shader)){
  if(n!=16||!scale_colour(v+7)||!scale_colour(v+8))return 0;
  for(UINT j=0;j<n;j++)if(v[j].kind!=(j<2||j>=7&&j<=10||j==15?1:j>=11?3:2))return 0;
  return 1;
 }
 if(!frame_final_shader(shader)||n!=14)return 0;
 for(UINT j=0;j<n;j++)if(v[j].kind!=(j==8?2:1))return 0;
 for(UINT j=offset[3];j<n;j++)if(v[j].r&&!scale_colour(v+j))return 0;
 if(!v[8].r||v[8].counter||v[8].d.uav.ViewDimension!=D3D12_UAV_DIMENSION_TEXTURE2D||v[8].d.uav.Texture2D.MipSlice||v[8].d.uav.Texture2D.PlaneSlice)return 0;
 D3D12_RESOURCE_DESC d=ID3D12Resource_GetDesc(v[8].r);
 return d.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D&&d.Width==mfg_output_w&&d.Height==mfg_output_h&&d.DepthOrArraySize==1&&d.MipLevels==1&&d.SampleDesc.Count==1&&d.Format==v[8].d.uav.Format&&frame_format_supported(d.Format);
}
static int scale_check_bindings(ID3D12GraphicsCommandList*l,uint64_t shader){
 struct scale_view*v=calloc(SCALE_VIEWS,sizeof(*v));if(!v)return 0;UINT n=0,offset[9]={0},ri=0;
 AcquireSRWLockExclusive(&frame_lock);AcquireSRWLockShared(&model_lock);AcquireSRWLockExclusive(&scale_lock);
 int ok=scale_snapshot_locked(l,shader,v,&n,offset,&ri)&&scale_resources_valid(shader,v,n,offset);
 ReleaseSRWLockExclusive(&scale_lock);ReleaseSRWLockShared(&model_lock);ReleaseSRWLockExclusive(&frame_lock);free(v);return ok;
}
static void scale_invalidate(void){
 if(!scale_enabled)return;
 AcquireSRWLockExclusive(&scale_lock);scale_epoch++;scale_qualified=scale_failed=0;ReleaseSRWLockExclusive(&scale_lock);
}
static void scale_block(const char*why){
 AcquireSRWLockExclusive(&scale_lock);
 if(scale_failed!=scale_epoch){logline("FREEFG_SCALE fallback: ");logline(why);logline("; full output retained\n");}
 scale_failed=scale_epoch;scale_qualified=0;scale_last_mode=3;ReleaseSRWLockExclusive(&scale_lock);
 mfg_settings_note_generated(mfg_output_w,mfg_output_h);
}
static void scale_report_full(UINT w,UINT h){
 AcquireSRWLockExclusive(&scale_lock);
 if(scale_last_mode!=2||scale_last_output_w!=w||scale_last_output_h!=h){
  char line[180];snprintf(line,sizeof(line),"FREEFG_SCALE full output=%ux%u generated=%ux%u reason=inside configured limit\n",w,h,w,h);logline(line);
 }
 scale_last_mode=2;scale_last_output_w=w;scale_last_output_h=h;
 ReleaseSRWLockExclusive(&scale_lock);
}
static UINT scale_begin_graph(ID3D12GraphicsCommandList*l){
 struct scale_view*v=calloc(SCALE_VIEWS,sizeof(*v));if(!v)return 0;UINT n=0,offset[9]={0},ri=0,mode=0;
 AcquireSRWLockExclusive(&frame_lock);AcquireSRWLockShared(&model_lock);AcquireSRWLockExclusive(&scale_lock);
 if(!scale_shader_failed&&scale_snapshot_locked(l,0xbc7a0d422d51c159ULL,v,&n,offset,&ri)&&scale_resources_valid(0xbc7a0d422d51c159ULL,v,n,offset)){
  UINT format=(UINT)v[0].d.srv.Format;
  if(scale_key_w!=mfg_output_w||scale_key_h!=mfg_output_h||scale_key_format!=format){scale_key_w=mfg_output_w;scale_key_h=mfg_output_h;scale_key_format=format;scale_epoch++;scale_qualified=scale_failed=0;}
  if(scale_failed!=scale_epoch){mode=scale_qualified==scale_epoch?2:1;scale_observing=scale_epoch;}
 }
 if(mode==2){if(scale_graph==UINT64_MAX)model_fail("scaling graph serial overflow");scale_graph++;}
 ReleaseSRWLockExclusive(&scale_lock);ReleaseSRWLockShared(&model_lock);ReleaseSRWLockExclusive(&frame_lock);free(v);
 if(!mode)scale_block("unsupported or previously rejected input layout");return mode;
}
static void scale_observation_done(void){
 AcquireSRWLockExclusive(&scale_lock);
 if(scale_observing==scale_epoch&&scale_failed!=scale_epoch){scale_qualified=scale_epoch;logline("FREEFG_SCALE observed complete full-output graph; scaling eligible next frame\n");}
 ReleaseSRWLockExclusive(&scale_lock);
}
static int scale_dispatch(ID3D12GraphicsCommandList*l,uint64_t shader,UINT x,UINT y,UINT z){
 if(!scale_enabled||!flow_cap_enabled)return 0;
 UINT fl=flow_slot(l);if(!flow_lists[fl].active||!mfg_scale_actual[fl])return 0;
 ID3D12RootSignature*root=flow_lists[fl].root;UINT li=frame_list(l);
 AcquireSRWLockExclusive(&frame_lock);AcquireSRWLockShared(&model_lock);AcquireSRWLockExclusive(&scale_lock);
 struct scale_view*views=calloc(SCALE_VIEWS,sizeof(*views));if(!views)model_fail("scaling view snapshot allocation");UINT n=0,offset[9]={0},ri=0;
 if(!scale_snapshot_locked(l,shader,views,&n,offset,&ri)||!scale_resources_valid(shader,views,n,offset))model_fail("scaling binding changed after observation");
 ReleaseSRWLockShared(&model_lock);
 if(frame_final_shader(shader)){
  /* Keep the SDK output identity in the snapshot. Only the private descriptor
   * points at the enlargement input, whose format and shader arithmetic match. */
  ReleaseSRWLockExclusive(&scale_lock);
  frame_initialize_output(views[8].d.uav.Format,mfg_cap_w,mfg_cap_h);
  ReleaseSRWLockExclusive(&frame_lock);AcquireSRWLockExclusive(&scale_lock);
 }else ReleaseSRWLockExclusive(&frame_lock);
 if(shader==0xbc7a0d422d51c159ULL&&(scale_last_mode!=1||scale_last_epoch!=scale_epoch||scale_last_output_w!=mfg_output_w||scale_last_output_h!=mfg_output_h||scale_last_w!=mfg_cap_w||scale_last_h!=mfg_cap_h||scale_last_format!=(UINT)views[0].d.srv.Format)){
  scale_collect_locked(1);scale_last_w=mfg_cap_w;scale_last_h=mfg_cap_h;scale_last_format=(UINT)views[0].d.srv.Format;
  scale_last_mode=1;scale_last_epoch=scale_epoch;scale_last_output_w=mfg_output_w;scale_last_output_h=mfg_output_h;
  char line[180];snprintf(line,sizeof(line),"FREEFG_SCALE active output=%ux%u generated=%ux%u down=%u up=%u\n",mfg_output_w,mfg_output_h,mfg_cap_w,mfg_cap_h,mfg_settings_applied.downscale,mfg_settings_applied.upscale);logline(line);
 }
 struct scale_batch*b;
 for(b=scale_batches;b;b=b->next)if(b->root==root&&b->w==mfg_cap_w&&b->h==mfg_cap_h&&b->n==n&&!memcmp(b->views,views,n*sizeof(*views)))break;
 UINT stride=ID3D12Device_GetDescriptorHandleIncrementSize(frame_device,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 if(!b){
  scale_collect_locked(0);
  if(scale_batch_count==512)model_fail("scaling in-flight batch capacity");
  b=calloc(1,sizeof(*b));if(!b)model_fail("scaling batch allocation");
  b->root=root;b->w=mfg_cap_w;b->h=mfg_cap_h;b->n=n;
  memcpy(b->views,views,n*sizeof(*views));memcpy(b->offset,offset,sizeof(offset));memcpy(b->count,scale_roots[ri].count,sizeof(b->count));
  if(frame_final_shader(shader)){b->direct_output=frame_temp;ID3D12Resource_AddRef(b->direct_output);}
  D3D12_DESCRIPTOR_HEAP_DESC hd={.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,.NumDescriptors=n*3,.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE};
  HR(model_heap_original(frame_device,&hd,&IID_ID3D12DescriptorHeap,(void**)&b->heap));
  SIZE_T cpu=ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(b->heap).ptr;UINT colors=0;
  for(UINT j=0;j<n;j++){
   struct scale_view*v=&b->views[j];D3D12_CPU_DESCRIPTOR_HANDLE dst={cpu+(SIZE_T)j*stride};
   if(v->r)ID3D12Resource_AddRef(v->r);if(v->counter)ID3D12Resource_AddRef(v->counter);
   if(scale_colour(v)&&(!frame_final_shader(shader)||j>=offset[3])){
    b->images[j]=scale_image_get(v,b->w,b->h);
    D3D12_RESOURCE_DESC rd=ID3D12Resource_GetDesc(b->images[j]->low);
    D3D12_SHADER_RESOURCE_VIEW_DESC sd={.Format=rd.Format,.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D,.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING,.Texture2D={.MipLevels=1}};
    scale_srv_raw(frame_device,b->images[j]->low,&sd,dst);
    b->filters[j]=n+colors*2;D3D12_CPU_DESCRIPTOR_HANDLE src={cpu+(SIZE_T)b->filters[j]*stride};scale_srv_raw(frame_device,v->r,&v->d.srv,src);
    src.ptr+=stride;D3D12_UNORDERED_ACCESS_VIEW_DESC ud={.Format=rd.Format,.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D};scale_uav_raw(frame_device,b->images[j]->low,NULL,&ud,src);colors++;
   }
   else if(frame_final_shader(shader)&&j==8)scale_uav_raw(frame_device,b->direct_output,NULL,&v->d.uav,dst);
   else if(v->kind==1)scale_srv_raw(frame_device,v->r,&v->d.srv,dst);
   else if(v->kind==2)scale_uav_raw(frame_device,v->r,v->counter,&v->d.uav,dst);
   else scale_cbv_raw(frame_device,&v->d.cbv,dst);
  }
  if(scale_batch_count<3)for(UINT j=0;j<n;j++){
   struct scale_view*v=&b->views[j];D3D12_RESOURCE_DESC rd=v->r?ID3D12Resource_GetDesc(v->r):(D3D12_RESOURCE_DESC){0};
   char info[240];snprintf(info,sizeof(info),"SCALE_VIEW shader=%016llx slot=%u kind=%u resource=%p format=%u size=%llux%u lower=%u\n",(unsigned long long)shader,j,v->kind,v->r,(UINT)rd.Format,(unsigned long long)rd.Width,rd.Height,!!b->images[j]);logline(info);
  }
  b->next=scale_batches;scale_batches=b;scale_batch_count++;
  char line[160];snprintf(line,sizeof(line),"FREEFG_SCALE_BIND shader=%016llx views=%u colors=%u size=%ux%u batches=%u\n",(unsigned long long)shader,n,colors,b->w,b->h,scale_batch_count);logline(line);
 }
 if(frame_final_shader(shader)&&b->direct_output!=frame_temp)model_fail("direct scaled output allocation changed");

 free(views);scale_note_batch(l,b);scale_filter_init();
 ID3D12PipelineState*original=NULL;for(UINT j=0;j<nbinding;j++)if(bindings[j].l==l)original=bindings[j].p;
 if(!original)model_fail("scaling missing pipeline");
 UINT64 gpu=ID3D12DescriptorHeap_GetGPUDescriptorHandleForHeapStart(b->heap).ptr;
 frame_heaps_original(l,1,&b->heap);flow_root_original(l,scale_filter_root);set_original(l,scale_filter_pso);
 for(UINT j=0;j<n;j++)if(b->images[j]){
  UINT duplicate=0;for(UINT k=0;k<j;k++)duplicate|=b->images[k]==b->images[j];if(duplicate)continue;
  /* The SDK's tagged scene inputs stay read-only through this frame's graph.
   * Preprocessing, warping and final composition can share their reduction on
   * one command list. A new frame/list or a texture copy invalidates reuse. */
  if(b->images[j]->sampled_graph==scale_graph&&b->images[j]->sampled_list==l)continue;
  if(scale_history_reusable(b->images[j],l)){
   scale_history_hits++;
   b->images[j]->sampled_graph=scale_graph;b->images[j]->sampled_list=l;continue;
  }

  scale_low_transition(l,b->images[j]->low,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  D3D12_GPU_DESCRIPTOR_HANDLE h={gpu+(UINT64)b->filters[j]*stride};frame_table_original(l,0,h);h.ptr+=stride;frame_table_original(l,1,h);
  dispatch_original(l,(b->w+7)/8,(b->h+7)/8,1);scale_resamples++;
  scale_low_transition(l,b->images[j]->low,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

  b->images[j]->sampled_graph=scale_graph;b->images[j]->sampled_list=l;
  b->images[j]->low_valid=1;b->images[j]->low_pending=1;
 }
 flow_root_original(l,root);
 for(UINT j=0;j<9;j++){
  if(b->count[j]){D3D12_GPU_DESCRIPTOR_HANDLE h={gpu+(UINT64)b->offset[j]*stride};frame_table_original(l,j,h);}
  else if(flow_lists[fl].mask[j]){
   UINT len=0;for(UINT k=0;k<64;k++)if(flow_lists[fl].mask[j]&(1ULL<<k))len=k+1;
   flow_constants_original(l,j,len,flow_lists[fl].scaled[j],0);
  }
 }
 set_original(l,original);dispatch_original(l,x,y,z);scale_dispatches++;
 if(scale_dispatches%1800==0){char line[160];snprintf(line,sizeof(line),"FREEFG_SCALE work dispatches=%llu resamples=%llu\n",(unsigned long long)scale_dispatches,(unsigned long long)scale_resamples);logline(line);}
 frame_heaps_original(l,frame_lists[li].heap_count,frame_lists[li].heaps);
 for(UINT j=0;j<9;j++)if(b->count[j]){D3D12_GPU_DESCRIPTOR_HANDLE h={frame_lists[li].table[j]};frame_table_original(l,j,h);}
 ReleaseSRWLockExclusive(&scale_lock);
 if(frame_final_shader(shader))frame_finish_dispatch(l,shader);
 return 1;
}
static void scale_release(void){
 {char line[120];snprintf(line,sizeof(line),"SCALE_HISTORY reused_reductions=%llu\n",(unsigned long long)scale_history_hits);logline(line);scale_history_hits=0;}
 for(UINT i=0;i<scale_unet_count;i++){
  char row[140];snprintf(row,sizeof(row),"FREEFG_SCALE_UNET shader=%016llx dispatches=%llu\n",(unsigned long long)scale_unet[i].shader,(unsigned long long)scale_unet[i].calls);logline(row);
  ID3D12PipelineState_Release(scale_unet[i].bounded);ID3D12PipelineState_Release(scale_unet[i].original);
 }
 memset(scale_unet,0,sizeof(scale_unet));scale_unet_count=scale_shader_failed=0;
 for(UINT i=0;i<scale_list_count;i++){struct scale_use*u=scale_lists[i].uses;while(u){struct scale_use*n=u->next;free(u);u=n;}}
 memset(scale_lists,0,sizeof(scale_lists));scale_list_count=0;
 while(scale_batches){struct scale_batch*b=scale_batches;scale_batches=b->next;scale_free_batch(b);}
 for(UINT i=0;i<scale_root_count;i++)ID3D12RootSignature_Release(scale_roots[i].r);
 if(scale_filter_pso)ID3D12PipelineState_Release(scale_filter_pso);if(scale_filter_root)ID3D12RootSignature_Release(scale_filter_root);
 if(scale_fence)ID3D12Fence_Release(scale_fence);scale_fence=NULL;scale_serial=0;
 char line[200];snprintf(line,sizeof(line),"FREEFG_SCALE completed_dispatches=%llu resamples=%llu recycled_batches=%llu\n",(unsigned long long)scale_dispatches,(unsigned long long)scale_resamples,(unsigned long long)scale_recycled);logline(line);
 scale_dispatches=scale_resamples=scale_recycled=scale_graph=0;scale_last_w=scale_last_h=scale_last_format=0;scale_epoch=1;scale_qualified=scale_failed=scale_observing=0;scale_key_w=scale_key_h=scale_key_format=0;
 scale_last_mode=scale_last_output_w=scale_last_output_h=0;scale_last_epoch=0;
 mfg_native_repeat_ready=0;mfg_scale_frame_actual=0;memset(mfg_scale_actual,0,sizeof(mfg_scale_actual));
 scale_filter_pso=NULL;scale_filter_root=NULL;scale_batch_count=scale_root_count=scale_descriptor_count=0;
 memset(scale_roots,0,sizeof(scale_roots));memset(scale_descriptors,0,sizeof(scale_descriptors));
}
