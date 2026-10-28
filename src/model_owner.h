/* SPDX-License-Identifier: MIT
 * Probe-only owner for the pinned SDK's coefficient buffers.
 * Dedicated DEFAULT allocations prevent heap aliasing. The original byte prefix
 * and expanded coefficients are uploaded from the SAME private CPU snapshot.
 * All later writes and unexpected descriptor layouts are fatal. This is a
 * qualification harness, not a general SDK interception/distribution layer.
 */
#define MODEL_BYTES 451584u
#define MODEL_ELEMENTS (MODEL_BYTES/16)
static UINT model_owner_enabled,model_count,model_allocations_open;
static ID3D12Device*model_device;
#define MODEL_CAPACITY 128
/* preparing: a pooled model published before its upload is recorded (mfg_pool_copy); not yet part of any set. */
static struct model_record {ID3D12Resource*r,*upload;UINT initialized,bytes,expanded,preparing;UINT64 va;} models[MODEL_CAPACITY];
static SRWLOCK model_lock=SRWLOCK_INIT;
static void model_fail(const char*why){logline("FAIL model owner: ");logline(why);logline("\n");ExitProcess(60);}
#include "mfg_model_alias.h"
static struct model_record*model_find(ID3D12Resource*r){
 for(UINT i=0;i<model_count;i++)if(models[i].r==r)return &models[i];
 struct mfg_model_alias*a=mfg_model_alias_find(r);if(a){if(!a->initialized)model_fail("model accessed before snapshot");return a->model;}
 return NULL;
}
static __typeof__(placed_original) model_placed_original;
static __typeof__(committed_original) model_committed_original;
static __typeof__(copy_original) model_copy_original;
static __typeof__(srv_original) model_srv_original;
static __typeof__(uav_original) model_uav_original;
static __typeof__(copy_texture_original) model_texture_original;
static __typeof__(copy_resource_original) model_resource_original;
static uint16_t model_half(int8_t v){UINT magnitude=v<0?-(int)v:v;if(!magnitude)return 0;UINT exponent=0;while((1u<<(exponent+1))<=magnitude)exponent++;return (v<0?0x8000:0)|((exponent+15)<<10)|((magnitude-(1u<<exponent))<<(10-exponent));}
static void(STDMETHODCALLTYPE*model_write_original)(ID3D12GraphicsCommandList2*,UINT,const D3D12_WRITEBUFFERIMMEDIATE_PARAMETER*,const D3D12_WRITEBUFFERIMMEDIATE_MODE*);
#include "model_bindings.h"
/* The multi-frame proxy meets Intel's runtime without the XeSSMFG enabler: it may hold only the 2x model (the 27-buffer
 * native set: 2x on this GPU, or another module that keeps the 2x model at every frame count), only the multi-frame model,
 * or both. A reader needs the complete set of its own model: the multi-frame readers 8 and 9 coefficient buffers of
 * their sizes, the 2x readers 6 and 7 (model_expected_count without XEFG_MFG_RESEARCH). */
static int model_mfg_reader(uint64_t shader){return shader==0x3c5180037dafdbb8ULL||shader==0x8b17a4f9fcb35e18ULL||shader==0x990b9bf8cf279d27ULL||shader==0x4470217240e7372aULL;}
static UINT model_native_count(UINT bytes){return bytes==451584?6:bytes==36864?7:0;}
static UINT model_expected_count(UINT bytes){
 if(bytes==451584)return 8;if(bytes==36864)return 9;
 switch(bytes){case 451584:return 6;case 73728:return 2;case 36864:return 7;case 18432:return 3;case 9216:return 1;case 4608:return 3;case 2304:return 5;default:return 0;}}
static UINT model_selected_size(UINT bytes){if(bytes==MODEL_BYTES)return 1;
if(model_owner_enabled>=2&&bytes==2304)return 1;if(model_owner_enabled>=4&&bytes==73728)return 1;return model_owner_enabled>=5&&(bytes==36864||bytes==18432||bytes==9216||bytes==4608);}

#include "model_winograd.h"
static UINT model_base_expanded(UINT bytes){return bytes*(bytes==MODEL_BYTES||model_owner_enabled==3?3:model_owner_enabled>=6&&bytes==36864?7:5);}
#include "model_wino_enc16.h"
static HRESULT STDMETHODCALLTYPE model_placed_hook(ID3D12Device*d,ID3D12Heap*h,UINT64 offset,const D3D12_RESOURCE_DESC*rd,D3D12_RESOURCE_STATES state,const D3D12_CLEAR_VALUE*clear,REFIID iid,void**out){
 /* MFG's game path prebuilds, then allocates a second model set when enabled.
  * Both sets use immutable snapshots; late uploads obey the same layout checks. */
 if(rd->Dimension!=D3D12_RESOURCE_DIMENSION_BUFFER||rd->Width>UINT32_MAX||rd->Flags!=D3D12_RESOURCE_FLAG_NONE||state!=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE||!model_selected_size((UINT)rd->Width))return model_placed_original(d,h,offset,rd,state,clear,iid,out);
 D3D12_HEAP_DESC heap=ID3D12Heap_GetDesc(h);
 if(rd->Flags||rd->Format!=DXGI_FORMAT_UNKNOWN||rd->Height!=1||rd->DepthOrArraySize!=1||rd->MipLevels!=1||rd->SampleDesc.Count!=1||rd->Layout!=D3D12_TEXTURE_LAYOUT_ROW_MAJOR||clear||heap.Properties.Type!=D3D12_HEAP_TYPE_DEFAULT||!IsEqualGUID(iid,&IID_ID3D12Resource))model_fail("unexpected model allocation");
 AcquireSRWLockExclusive(&model_lock);if(model_count==sizeof(models)/sizeof(*models))model_fail("too many model allocations");
 D3D12_RESOURCE_DESC copy=*rd;copy.Width=model_base_expanded((UINT)rd->Width);if(model_owner_enabled==7&&(rd->Width==MODEL_BYTES||rd->Width==36864))copy.Width+=model_winograd_size((UINT)rd->Width);copy.Width+=model_enc16_size((UINT)rd->Width);copy.Alignment=0;
 D3D12_HEAP_PROPERTIES hp=heap.Properties;
 HRESULT hr=model_committed_original(d,&hp,D3D12_HEAP_FLAG_NONE,&copy,state,NULL,iid,out);
 if(SUCCEEDED(hr)){struct model_record*m=&models[model_count++];m->r=*out;m->bytes=(UINT)rd->Width;m->expanded=(UINT)copy.Width;m->va=ID3D12Resource_GetGPUVirtualAddress(m->r);ID3D12Resource_AddRef(m->r);char line[180];snprintf(line,sizeof(line),"MODEL_ALLOC resource=%p original_bytes=%u expanded_bytes=%u va=%llx\n",m->r,m->bytes,m->expanded,(unsigned long long)m->va);logline(line);}
 ReleaseSRWLockExclusive(&model_lock);return hr;
}
static UINT model_pack(const int8_t*raw,uint32_t*expanded){
 UINT maximum=0;
 /* A four-dot block is four input packs for one tap/output group. Each
  * packed i16 lane consumes byte pair {0,1} or {2,3} over those four packs. */
 for(UINT base=0;base<MODEL_ELEMENTS;base+=4)for(UINT output=0;output<4;output++)for(UINT pair=0;pair<2;pair++){
  UINT sum=0;for(UINT pack=0;pack<4;pack++)for(UINT byte=0;byte<2;byte++){int value=raw[(base+pack)*16+output*4+pair*2+byte];sum+=(UINT)(value<0?-value:value);}
  if(sum>255)model_fail("coefficient bound exceeds exact i16 domain");if(sum>maximum)maximum=sum;
 }
 for(UINT element=0;element<MODEL_ELEMENTS;element++)for(UINT output=0;output<4;output++){
  const int8_t*v=raw+element*16+output*4;
  expanded[element*8+output]=(uint16_t)(int16_t)v[0]|((uint32_t)(uint16_t)(int16_t)v[2]<<16);
  expanded[element*8+4+output]=(uint16_t)(int16_t)v[1]|((uint32_t)(uint16_t)(int16_t)v[3]<<16);
 }
 return maximum;
}
/* A separate suffix preserves the FP32 ABI used by the modern kernels.
 * Each two-byte coefficient lane must bound one dot to signed i16. */
static UINT model_pack_refinement(const int8_t*raw,uint32_t*expanded){
 UINT maximum=0;
 for(UINT element=0;element<36864/16;element++)for(UINT output=0;output<4;output++){
  const int8_t*v=raw+element*16+output*4;
  for(UINT pair=0;pair<2;pair++){UINT sum=0;for(UINT lane=0;lane<2;lane++){int value=v[pair*2+lane];sum+=(UINT)(value<0?-value:value);}if(sum>255)model_fail("refinement coefficient bound exceeds exact i16 domain");if(sum>maximum)maximum=sum;}
  expanded[element*8+output]=(uint16_t)(int16_t)v[0]|((uint32_t)(uint16_t)(int16_t)v[2]<<16);
  expanded[element*8+4+output]=(uint16_t)(int16_t)v[1]|((uint32_t)(uint16_t)(int16_t)v[3]<<16);
 }
 return maximum;
}
static void STDMETHODCALLTYPE model_copy_hook(ID3D12GraphicsCommandList*l,ID3D12Resource*dst,UINT64 doffset,ID3D12Resource*src,UINT64 soffset,UINT64 size){
 AcquireSRWLockExclusive(&model_lock);struct model_record*m=model_find(dst);
 if(!m){ReleaseSRWLockExclusive(&model_lock);model_copy_original(l,dst,doffset,src,soffset,size);return;}
 if(m->initialized||doffset||soffset||size!=m->bytes)model_fail("model rewrite or partial upload");
 D3D12_HEAP_PROPERTIES hp;D3D12_HEAP_FLAGS flags;HR(ID3D12Resource_GetHeapProperties(src,&hp,&flags));D3D12_RESOURCE_DESC rd=ID3D12Resource_GetDesc(src);
 if(hp.Type!=D3D12_HEAP_TYPE_UPLOAD||rd.Dimension!=D3D12_RESOURCE_DIMENSION_BUFFER||rd.Width!=m->bytes)model_fail("model source is not the expected upload");
 void*source,*snapshot;D3D12_RANGE read={0,m->bytes},none={0,0};HR(ID3D12Resource_Map(src,0,&read,&source));
 /* No caller can see this upload pointer. Its lifetime lasts to process exit. */
 m->upload=buffer(model_device,m->expanded,D3D12_HEAP_TYPE_UPLOAD);HR(ID3D12Resource_Map(m->upload,0,&none,&snapshot));memcpy(snapshot,source,m->bytes);ID3D12Resource_Unmap(src,0,&none);
 UINT maximum=0;if(m->bytes==MODEL_BYTES){
 /* MFG weights exceed the old packed-i16 bound. Only the separately checked
  * Winograd representation is consumed; original bytes remain intact. */
 memset((char*)snapshot+m->bytes,0,m->bytes*2);
 }else if(model_owner_enabled!=3){float*expanded=(float*)((char*)snapshot+m->bytes);for(UINT i=0;i<m->bytes;i++)expanded[i]=(float)((int8_t*)snapshot)[i];}else{uint16_t*expanded=(uint16_t*)((char*)snapshot+m->bytes);for(UINT i=0;i<m->bytes;i++)expanded[i]=model_half(((int8_t*)snapshot)[i]);}if(model_owner_enabled>=6&&m->bytes==36864)maximum=model_pack_refinement(snapshot,(uint32_t*)((char*)snapshot+m->bytes*5));if(model_owner_enabled==7&&(m->bytes==MODEL_BYTES||m->bytes==36864))model_winograd_pack(snapshot,(char*)snapshot+model_base_expanded(m->bytes),m->bytes);
 model_enc16_pack(snapshot,m->bytes,m->expanded);

 uint64_t digest=hash(snapshot,m->bytes);D3D12_RANGE written={0,m->expanded};ID3D12Resource_Unmap(m->upload,0,&written);
 m->initialized=1;char line[200];snprintf(line,sizeof(line),"MODEL_SNAPSHOT resource=%p hash=%016llx maximum_l1=%u bytes=%u\n",dst,(unsigned long long)digest,maximum,m->expanded);logline(line);
 model_copy_original(l,dst,0,m->upload,0,m->expanded);ReleaseSRWLockExclusive(&model_lock);
}
#include "mfg_model_pool.h"
static void STDMETHODCALLTYPE model_srv_hook(ID3D12Device*d,ID3D12Resource*r,const D3D12_SHADER_RESOURCE_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){
 AcquireSRWLockExclusive(&model_lock);struct model_record*m=model_find(r);model_descriptor_set(h.ptr,m);
 if(m){if(!m->initialized||!desc||desc->ViewDimension!=D3D12_SRV_DIMENSION_BUFFER||desc->Format!=DXGI_FORMAT_UNKNOWN||desc->Buffer.FirstElement||desc->Buffer.NumElements!=m->bytes/16||desc->Buffer.StructureByteStride!=16||desc->Buffer.Flags)model_fail("unexpected model SRV");D3D12_SHADER_RESOURCE_VIEW_DESC copy=*desc;copy.Buffer.NumElements=m->expanded/16;model_srv_original(d,m->r,&copy,h);}else model_srv_original(d,r,desc,h);
 ReleaseSRWLockExclusive(&model_lock);
}
static void STDMETHODCALLTYPE model_uav_hook(ID3D12Device*d,ID3D12Resource*r,ID3D12Resource*counter,const D3D12_UNORDERED_ACCESS_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){AcquireSRWLockExclusive(&model_lock);if(model_find(r)||model_find(counter))model_fail("model exposed for UAV writes");model_descriptor_set(h.ptr,NULL);ReleaseSRWLockExclusive(&model_lock);model_uav_original(d,r,counter,desc,h);}
static void STDMETHODCALLTYPE model_texture_hook(ID3D12GraphicsCommandList*l,const D3D12_TEXTURE_COPY_LOCATION*dst,UINT x,UINT y,UINT z,const D3D12_TEXTURE_COPY_LOCATION*src,const D3D12_BOX*box){AcquireSRWLockShared(&model_lock);if(model_find(dst->pResource))model_fail("texture copy into model");ReleaseSRWLockShared(&model_lock);
 scale_source_written(dst->pResource);
 model_texture_original(l,dst,x,y,z,src,box);}
static void STDMETHODCALLTYPE model_resource_hook(ID3D12GraphicsCommandList*l,ID3D12Resource*dst,ID3D12Resource*src){AcquireSRWLockShared(&model_lock);if(model_find(dst)||model_find(src))model_fail("whole-resource copy involving model");ReleaseSRWLockShared(&model_lock);
 scale_source_written(dst);
 model_resource_original(l,dst,src);
 scale_source_copied(dst);
}
static void STDMETHODCALLTYPE model_write_hook(ID3D12GraphicsCommandList2*l,UINT count,const D3D12_WRITEBUFFERIMMEDIATE_PARAMETER*p,const D3D12_WRITEBUFFERIMMEDIATE_MODE*m){for(UINT j=0;j<count;j++)for(UINT i=0;i<model_count;i++)if(p[j].Dest>=models[i].va&&p[j].Dest<models[i].va+models[i].expanded)model_fail("immediate write into model");model_write_original(l,count,p,m);}
static UINT model_shader_bytes(uint64_t shader){
 if(!model_owner_enabled)return 0;
 if(shader==0x3c5180037dafdbb8ULL||shader==0x8b17a4f9fcb35e18ULL)return MODEL_BYTES;
 if(shader==0x990b9bf8cf279d27ULL||shader==0x4470217240e7372aULL)return 36864;
 if(shader==0xfec421a3b6a0632bULL||shader==0x18a0d2663b5d5282ULL)return MODEL_BYTES;
 if(model_owner_enabled>=2&&(shader==0xb3941ac8ff95efe7ULL||shader==0x1a3b0782583fef19ULL||shader==0x60edebbbd2f9fb69ULL))return 2304;
 if(model_owner_enabled>=4&&(shader==0x1f27b449fb99a587ULL||shader==0x9e0080eee00255f2ULL))return 73728;
 if(model_owner_enabled>=6&&(shader==0x08155f47bc92811bULL||shader==0x558c3931ba6fb064ULL))return 36864;
 if(model_owner_enabled>=5){switch(shader){case 0xf030948d38e74671ULL:return 4608;case 0xe83e868f8d5d2c0fULL:case 0xf2e2e13fea432d20ULL:return 18432;case 0x4bb52a635e6d221aULL:return 36864;case 0x5654aa3800432b13ULL:return 9216;}}
 return 0;
}
static void model_dispatch_check(ID3D12GraphicsCommandList*l,uint64_t shader){UINT bytes=model_shader_bytes(shader);if(!bytes)return;AcquireSRWLockExclusive(&model_lock);UINT matching=0;for(UINT i=0;i<model_count;i++)if(models[i].bytes==bytes&&!models[i].preparing){matching++;if(!models[i].initialized){
  if(proxy_census_soft("a model reader met a model buffer that was never uploaded")){ReleaseSRWLockExclusive(&model_lock);return;}
  model_fail("uninitialized model");}}
 UINT expected=model_mfg_reader(shader)?model_expected_count(bytes):model_native_count(bytes);if(!expected)expected=model_expected_count(bytes);
 if(matching<expected){if(proxy_census_soft("a model reader met an incomplete model set")){ReleaseSRWLockExclusive(&model_lock);return;}model_fail("incomplete MFG model set");}
 model_binding_check(l,bytes);
 ReleaseSRWLockExclusive(&model_lock);}
static void model_seal_allocations(void){
 if(!model_owner_enabled)return;
 AcquireSRWLockExclusive(&model_lock);model_allocations_open=0;
 UINT initialized_count=model_count;
 initialized_count=mfg_initial_count;
 UINT expected=model_owner_enabled==1?6:model_owner_enabled>=5?27:model_owner_enabled==4?13:11;
 if(model_owner_enabled==7)expected=31;
 /* The enabler keeps the31-buffer MFG model and initializes the27-buffer
  * native2x model when2x is selected. Validate both complete size censuses. */
 /* Also the 2x model alone (27 buffers), which Intel's runtime initialises without the enabler. */
 if(initialized_count==58||initialized_count==27)expected=initialized_count;
 UINT native=initialized_count==58||initialized_count==27,mfg=initialized_count!=27;
 const UINT sizes[]={451584,36864,2304,4608,18432,73728,9216};
 const UINT native_counts[]={6,7,5,3,3,2,1},mfg_counts[]={8,9,5,3,3,2,1};
 for(UINT j=0;j<7;j++){
 UINT n=0;for(UINT i=0;i<model_count;i++)if(models[i].bytes==sizes[j])n++;
  n=mfg_initial_counts[j];
  if(n!=native*native_counts[j]+mfg*mfg_counts[j]){
   if(proxy_census_soft("the initial model census is not one this project verified")){ReleaseSRWLockExclusive(&model_lock);return;}
   model_fail("incomplete initial MFG/native model census");}}
 if(initialized_count!=expected){
  if(proxy_census_soft("the initial model count is not one this project verified")){ReleaseSRWLockExclusive(&model_lock);return;}
  model_fail("unexpected initialized model count");}
 ReleaseSRWLockExclusive(&model_lock);
 logline("MODEL_SEALED initial MFG set verified; later immutable sets remain eligible\n");
}
static void install_model_owner(ID3D12Device*d,ID3D12GraphicsCommandList*l){
 model_owner_enabled=env_uint("XEFG_MODEL_OWNER",0);
 if(model_owner_enabled&&(model_owner_enabled!=7||env_uint("XEFG_WINOGRAD",0)!=3))model_fail("MFG requires Winograd model owner");
 if(!model_owner_enabled)return;if(model_owner_enabled>7)model_fail("invalid mode");model_device=d;model_allocations_open=1;
 model_enc16_configure();
 install_model_bindings(d,l);
 model_placed_original=d->lpVtbl->CreatePlacedResource;model_committed_original=d->lpVtbl->CreateCommittedResource;model_copy_original=l->lpVtbl->CopyBufferRegion;model_srv_original=d->lpVtbl->CreateShaderResourceView;model_uav_original=d->lpVtbl->CreateUnorderedAccessView;model_texture_original=l->lpVtbl->CopyTextureRegion;model_resource_original=l->lpVtbl->CopyResource;
 replace((void*)&d->lpVtbl->CreatePlacedResource,mfg_pool_placed);replace((void*)&l->lpVtbl->CopyBufferRegion,mfg_pool_copy);
 replace((void*)&d->lpVtbl->CreateShaderResourceView,model_srv_hook);replace((void*)&d->lpVtbl->CreateUnorderedAccessView,model_uav_hook);replace((void*)&l->lpVtbl->CopyTextureRegion,model_texture_hook);replace((void*)&l->lpVtbl->CopyResource,model_resource_hook);
 ID3D12GraphicsCommandList2*l2=NULL;HR(ID3D12GraphicsCommandList_QueryInterface(l,&IID_ID3D12GraphicsCommandList2,(void**)&l2));model_write_original=l2->lpVtbl->WriteBufferImmediate;replace((void*)&l2->lpVtbl->WriteBufferImmediate,model_write_hook);ID3D12GraphicsCommandList2_Release(l2);
 logline("MODEL_OWNER snapshot-prefix-and-packed16 dedicated-allocation writes-fail-closed\n");
}
