/* SPDX-License-Identifier: MIT
 * Generated-frame cap. SDK allocations stay intact; synthesis writes a smaller
 * region, copied and enlarged AFTER generation. MFG uses an aspect-preserving
 * 1920x1080 bounding box; the archived non-MFG experiment remains fixed-size.
 * Immutable per-output descriptors and the existing single-queue fence owner
 * protect asynchronously consumed resources. Tester builds add input fallback.
 */
#include "frame_cap_contract.h"
static struct{ID3D12GraphicsCommandList*l;UINT64 table[9];UINT table_mask,heap_count;ID3D12DescriptorHeap*heaps[2];} frame_lists[128];static UINT frame_list_count;
static struct{SIZE_T cpu;ID3D12Resource*r;D3D12_UNORDERED_ACCESS_VIEW_DESC desc;UINT valid;} frame_descs[8192];static UINT frame_desc_count;
static struct{uint64_t shader;ID3D12PipelineState*original,*scaled;
} frame_psos[32];static UINT frame_pso_count;
static struct{ID3D12Resource*r;ID3D12DescriptorHeap*heap;UINT temp;} frame_outputs[64];static UINT frame_output_count;
/* Intermediate generated frames, one per (format, size). XeFG keeps its context across ResizeBuffers, so a resolution
 * change or an HDR toggle brings outputs of another size or format within one context; frame_temp is the one in use. */
static struct{ID3D12Resource*r;DXGI_FORMAT format;UINT w,h;} frame_temps[4];static UINT frame_temp_index;
static UINT frame_temp_w,frame_temp_h;
static ID3D12Device*frame_device;static ID3D12Resource*frame_temp,*frame_readback;static D3D12_PLACED_SUBRESOURCE_FOOTPRINT frame_footprint;static UINT64 frame_readback_size,frame_completed;
static ID3D12RootSignature*frame_root;static ID3D12PipelineState*frame_upscale;static DXGI_FORMAT frame_format;static SRWLOCK frame_lock=SRWLOCK_INIT;
static __typeof__(uav_original) frame_uav_original;static __typeof__(simple_original) frame_simple_original;static __typeof__(descs_original) frame_descs_original;static __typeof__(table_original) frame_table_original;
static void(STDMETHODCALLTYPE*frame_srv_original)(ID3D12Device*,ID3D12Resource*,const D3D12_SHADER_RESOURCE_VIEW_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE);
static void(STDMETHODCALLTYPE*frame_cbv_original)(ID3D12Device*,const D3D12_CONSTANT_BUFFER_VIEW_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE);
static void(STDMETHODCALLTYPE*frame_heaps_original)(ID3D12GraphicsCommandList*,UINT,ID3D12DescriptorHeap*const*);
static UINT frame_list(ID3D12GraphicsCommandList*l){for(UINT i=0;i<frame_list_count;i++)if(frame_lists[i].l==l)return i;if(frame_list_count==128)model_fail("frame list capacity");UINT i=frame_list_count++;frame_lists[i].l=l;return i;}
static void frame_root_changed(ID3D12GraphicsCommandList*l){AcquireSRWLockExclusive(&frame_lock);frame_lists[frame_list(l)].table_mask=0;ReleaseSRWLockExclusive(&frame_lock);}
static void frame_reset_list(ID3D12GraphicsCommandList*l){AcquireSRWLockExclusive(&frame_lock);UINT i=frame_list(l);frame_lists[i].table_mask=frame_lists[i].heap_count=0;ReleaseSRWLockExclusive(&frame_lock);}
static UINT frame_desc(SIZE_T cpu){for(UINT i=0;i<frame_desc_count;i++)if(frame_descs[i].cpu==cpu)return i;if(frame_desc_count==8192)model_fail("frame descriptor capacity");UINT i=frame_desc_count++;frame_descs[i].cpu=cpu;return i;}
/* A descriptor slot can change type. Never retain a stale UAV resource when
 * the SDK reuses the slot for an SRV or CBV, including null descriptors. */
static void frame_remove_descriptor_locked(SIZE_T cpu){for(UINT i=0;i<frame_desc_count;i++)if(frame_descs[i].cpu==cpu){frame_descs[i]=frame_descs[--frame_desc_count];memset(&frame_descs[frame_desc_count],0,sizeof(*frame_descs));break;}}
static void frame_clear_uav(SIZE_T cpu){AcquireSRWLockExclusive(&frame_lock);frame_remove_descriptor_locked(cpu);ReleaseSRWLockExclusive(&frame_lock);}
static void STDMETHODCALLTYPE frame_srv_hook(ID3D12Device*d,ID3D12Resource*r,const D3D12_SHADER_RESOURCE_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){frame_clear_uav(h.ptr);frame_srv_original(d,r,desc,h);}
static void STDMETHODCALLTYPE frame_cbv_hook(ID3D12Device*d,const D3D12_CONSTANT_BUFFER_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){frame_clear_uav(h.ptr);frame_cbv_original(d,desc,h);}
static void STDMETHODCALLTYPE frame_uav_hook(ID3D12Device*d,ID3D12Resource*r,ID3D12Resource*counter,const D3D12_UNORDERED_ACCESS_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){
/* Intermediate UAV formats do not describe the generated output. Validate
  * the actual final-output descriptor in frame_output_layout instead. */
 UINT valid=r&&desc&&!counter&&desc->ViewDimension==D3D12_UAV_DIMENSION_TEXTURE2D&&!desc->Texture2D.MipSlice&&!desc->Texture2D.PlaneSlice;
 AcquireSRWLockExclusive(&frame_lock);
 if(!valid)frame_remove_descriptor_locked(h.ptr);else
 {UINT i=frame_desc(h.ptr);frame_descs[i].valid=valid;frame_descs[i].r=r;if(desc)frame_descs[i].desc=*desc;}
 ReleaseSRWLockExclusive(&frame_lock);frame_uav_original(d,r,counter,desc,h);
}
static void frame_copy_descriptor(SIZE_T dst,SIZE_T src){
 UINT from;for(from=0;from<frame_desc_count;from++)if(frame_descs[from].cpu==src)break;
 if(from==frame_desc_count||!frame_descs[from].valid){frame_remove_descriptor_locked(dst);return;}
 UINT to=frame_desc(dst);
 frame_descs[to].r=frame_descs[from].r;frame_descs[to].desc=frame_descs[from].desc;frame_descs[to].valid=frame_descs[from].valid;
}
static void STDMETHODCALLTYPE frame_simple_hook(ID3D12Device*d,UINT n,D3D12_CPU_DESCRIPTOR_HANDLE dst,D3D12_CPU_DESCRIPTOR_HANDLE src,D3D12_DESCRIPTOR_HEAP_TYPE type){if(type==D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV){UINT stride=ID3D12Device_GetDescriptorHandleIncrementSize(d,type);AcquireSRWLockExclusive(&frame_lock);for(UINT i=0;i<n;i++)frame_copy_descriptor(dst.ptr+(SIZE_T)i*stride,src.ptr+(SIZE_T)i*stride);ReleaseSRWLockExclusive(&frame_lock);}frame_simple_original(d,n,dst,src,type);}
static void STDMETHODCALLTYPE frame_descs_hook(ID3D12Device*d,UINT nd,const D3D12_CPU_DESCRIPTOR_HANDLE*dst,const UINT*dn,UINT ns,const D3D12_CPU_DESCRIPTOR_HANDLE*src,const UINT*sn,D3D12_DESCRIPTOR_HEAP_TYPE type){
 if(type==D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV){UINT si=0,so=0,stride=ID3D12Device_GetDescriptorHandleIncrementSize(d,type);AcquireSRWLockExclusive(&frame_lock);for(UINT di=0;di<nd;di++)for(UINT off=0;off<(dn?dn[di]:1);off++){if(si>=ns)model_fail("frame descriptor ranges");frame_copy_descriptor(dst[di].ptr+(SIZE_T)off*stride,src[si].ptr+(SIZE_T)so*stride);if(++so==(sn?sn[si]:1)){si++;so=0;}}ReleaseSRWLockExclusive(&frame_lock);}frame_descs_original(d,nd,dst,dn,ns,src,sn,type);
}
static void STDMETHODCALLTYPE frame_table_hook(ID3D12GraphicsCommandList*l,UINT index,D3D12_GPU_DESCRIPTOR_HANDLE h){if(index<9){AcquireSRWLockExclusive(&frame_lock);UINT i=frame_list(l);frame_lists[i].table[index]=h.ptr;frame_lists[i].table_mask|=1u<<index;ReleaseSRWLockExclusive(&frame_lock);}frame_table_original(l,index,h);}
static void STDMETHODCALLTYPE frame_heaps_hook(ID3D12GraphicsCommandList*l,UINT n,ID3D12DescriptorHeap*const*h){if(n>2)model_fail("frame heap count");AcquireSRWLockExclusive(&frame_lock);UINT i=frame_list(l);frame_lists[i].heap_count=n;for(UINT j=0;j<n;j++)frame_lists[i].heaps[j]=h[j];ReleaseSRWLockExclusive(&frame_lock);frame_heaps_original(l,n,h);}
static void install_frame_cap(ID3D12Device*d,ID3D12GraphicsCommandList*l){
 if(!d||graph_enabled!=3)model_fail("full frame cap needs the accelerated single-queue owner");frame_device=d;
 frame_uav_original=d->lpVtbl->CreateUnorderedAccessView;replace((void*)&d->lpVtbl->CreateUnorderedAccessView,frame_uav_hook);
 frame_srv_original=d->lpVtbl->CreateShaderResourceView;replace((void*)&d->lpVtbl->CreateShaderResourceView,frame_srv_hook);
 frame_cbv_original=d->lpVtbl->CreateConstantBufferView;replace((void*)&d->lpVtbl->CreateConstantBufferView,frame_cbv_hook);
 frame_simple_original=d->lpVtbl->CopyDescriptorsSimple;replace((void*)&d->lpVtbl->CopyDescriptorsSimple,frame_simple_hook);
 frame_descs_original=d->lpVtbl->CopyDescriptors;replace((void*)&d->lpVtbl->CopyDescriptors,frame_descs_hook);
 frame_table_original=l->lpVtbl->SetComputeRootDescriptorTable;replace((void*)&l->lpVtbl->SetComputeRootDescriptorTable,frame_table_hook);
 frame_heaps_original=l->lpVtbl->SetDescriptorHeaps;replace((void*)&l->lpVtbl->SetDescriptorHeaps,frame_heaps_hook);
 logline("FRAME_CAP generated-frame scaling armed; raw engine inputs preserved\n");
}
static int frame_warp_shader(uint64_t shader){
 return shader==0x3a7d9dfa831ba4f3ULL||shader==0x8809b169edee2ba8ULL
 ||shader==0xe3914510b21e5419ULL||shader==0x72d9e71a91664cccULL||shader==0x44a0f8def607bdf5ULL
 ||shader==0xf440a4f4a7311d91ULL||shader==0xf9c944580da4662dULL
 /* HDR10 warps: 2x 276a73a0/0044a8b4, 3x/4x fda36bb6/c3824a65 (mfg_geometry_shader). */
 ||shader==0x276a73a0ff428af4ULL||shader==0x0044a8b41303a9f7ULL||shader==0xfda36bb6a452bbc1ULL||shader==0xc3824a65b3d90388ULL
 ;
}
static int frame_final_shader(uint64_t shader){return shader==0x977942d5d9337711ULL||shader==0x7da098e8e69a54f8ULL;}
static int frame_scatter_shader(uint64_t shader){
 return shader==0x437542192dd795c8ULL||shader==0x995b75ef9d54204aULL
 ||shader==0x8c09ff6372805dbfULL
 ;
}
static void frame_capture_pso(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,uint64_t shader,ID3D12PipelineState*original){
 if(!env_uint("XEFG_FLOW_CAP",0)||(!frame_warp_shader(shader)&&!frame_final_shader(shader)))return;
 if(frame_final_shader(shader)&&env_uint("XEFG_FRAME_OUTPUT_ORACLE",0))return;
 if(frame_pso_count==sizeof(frame_psos)/sizeof(*frame_psos))model_fail("frame PSO capacity");char name[80];snprintf(name,sizeof(name),"frame-warp-%016llx.dxil",(unsigned long long)shader);UINT size;void*bytes=shader==0x44a0f8def607bdf5ULL?graph_blob(name,&size):frame_color_blob(name,&size);D3D12_COMPUTE_PIPELINE_STATE_DESC copy=*desc;copy.CS.pShaderBytecode=bytes;copy.CS.BytecodeLength=size;copy.CachedPSO=(D3D12_CACHED_PIPELINE_STATE){0};ID3D12PipelineState*p;HR(compute_original(d,&copy,&IID_ID3D12PipelineState,(void**)&p));free(bytes);frame_psos[frame_pso_count].shader=shader;frame_psos[frame_pso_count].original=original;frame_psos[frame_pso_count++].scaled=p;
}
static int frame_dispatch_pso(ID3D12GraphicsCommandList*l,uint64_t shader,UINT x,UINT y,UINT z){
 if(frame_final_shader(shader)&&env_uint("XEFG_FRAME_OUTPUT_ORACLE",0))return 0;
 if(!flow_cap_enabled||(!frame_warp_shader(shader)&&!frame_final_shader(shader)))return 0;AcquireSRWLockExclusive(&flow_lock);UINT active=flow_lists[flow_slot(l)].active;
 ReleaseSRWLockExclusive(&flow_lock);if(!active)return 0;
 ID3D12PipelineState*original=NULL;for(UINT i=0;i<nbinding;i++)if(bindings[i].l==l)original=bindings[i].p;
 for(UINT i=0;i<frame_pso_count;i++)if(frame_psos[i].original==original){
#ifndef XEFG_MFG_WARP_GROUP_X
#define XEFG_MFG_WARP_GROUP_X 8
#endif
#ifndef XEFG_MFG_WARP_GROUP_Y
#define XEFG_MFG_WARP_GROUP_Y 16
#endif
#if XEFG_MFG_WARP_GROUP_X != 8 || XEFG_MFG_WARP_GROUP_Y != 16
#if (XEFG_MFG_WARP_GROUP_X != 8 && XEFG_MFG_WARP_GROUP_X != 4) || (XEFG_MFG_WARP_GROUP_Y != 16 && XEFG_MFG_WARP_GROUP_Y != 8 && XEFG_MFG_WARP_GROUP_Y != 4) || XEFG_MFG_WARP_GROUP_X*XEFG_MFG_WARP_GROUP_Y < 32
#error Unsupported capped MFG warp group shape
#endif
 /* This point is reached only for an active cap replacement. The SDK's
  * original shader keeps its dispatch shape for full/lower-resolution paths. */
 if(shader==0xe3914510b21e5419ULL){
  const UINT sx=8/XEFG_MFG_WARP_GROUP_X,sy=16/XEFG_MFG_WARP_GROUP_Y;
  if(z!=1||x>65535/sx||y>65535/sy)model_fail("capped MFG warp dispatch bounds");
  x*=sx;y*=sy;
 }
#endif
 set_original(l,frame_psos[i].scaled);
 dispatch_original(l,x,y,z);
 set_original(l,original);if(frame_final_shader(shader))frame_finish_dispatch(l,shader);
 mfg_capture_dispatch(l,shader);
 return 1;}model_fail("missing full-frame warp PSO");return 0;
}
static void frame_float(UINT*p,float value){memcpy(p,&value,4);}
/* Called with flow_lock held, before model checks and ordinary dispatch retile. */
static void frame_prepare_dispatch(ID3D12GraphicsCommandList*l,uint64_t shader,UINT*x,UINT*y,UINT*z,UINT*step){
 UINT i=flow_slot(l);if(*step==23){if(!frame_scatter_shader(shader))model_fail("missing native motion scatter");(*step)++;return;}
 if(*step==24){
  if(!frame_warp_shader(shader))model_fail("missing full-frame warp");
  UINT c[51];if((flow_lists[i].mask[6]&((1ULL<<51)-1))!=((1ULL<<51)-1))model_fail("frame warp constants");memcpy(c,flow_lists[i].values[6],sizeof(c));
  if(c[0]||c[1]||c[4]||c[5]||c[2]!=2560||c[3]!=1440||c[6]!=2560||c[7]!=1440||c[8]!=2560||c[9]!=1440||c[36]!=640||c[37]!=360||c[46]!=640||c[47]!=0x40800000||c[49])model_fail("unsupported full-frame source geometry / high-res MV");
  if(!c[12]||!c[13]||c[12]>1920||c[13]>1080||!c[16]||!c[17]||c[16]>1920||c[17]>1080)model_fail("full-frame engine input too large");
  c[2]=c[6]=c[8]=c[38]=1920;c[3]=c[7]=c[9]=c[39]=1080;
  frame_float(c+10,1.f/1920);frame_float(c+11,1.f/1080);
  float sx,sy;memcpy(&sx,c+26,4);memcpy(&sy,c+27,4);frame_float(c+26,sx*.75f);frame_float(c+27,sy*.75f);
  c[28]=c[30]=960;c[29]=c[31]=540;c[36]=c[46]=480;c[37]=272;
  for(UINT j=40;j<46;j+=2){frame_float(c+j,1.f/1920);frame_float(c+j+1,1.f/1080);}
  flow_constants_original(l,6,51,c,0);*x=120;*y=34;*z=1;(*step)++;return;
 }
 if(*step<25||*step>=38)model_fail("full-frame synthesis ordering");UINT index=*step-25;
 if(frame_rows[index].shader!=shader&&!(index==12&&frame_final_shader(shader)))model_fail("full-frame synthesis shader differs");
 UINT ri=frame_rows[index].index,n=frame_rows[index].n,c[64];if((flow_lists[i].mask[ri]&((1ULL<<n)-1))!=((1ULL<<n)-1))model_fail("full-frame synthesis constants");memcpy(c,flow_lists[i].values[ri],n*4);
 UINT meaningful=frame_final_shader(shader)?n:2;
 if(frame_final_shader(shader)){
  for(UINT j=0;j<meaningful;j++){
   if(j==14){if(c[j]>5)model_fail("native UI mode");continue;}
   if(j==15){if(c[j]>1)model_fail("native marker mode");continue;}
   if(j==16)continue;
   if(c[j]!=frame_rows[index].old[j])model_fail("native final geometry");c[j]=frame_rows[index].target[j];
  }
 }else
 {if(memcmp(c,frame_rows[index].old,meaningful*4))model_fail("full-frame synthesis layout differs");memcpy(c,frame_rows[index].target,meaningful*4);}
 flow_constants_original(l,ri,n,c,0);*x=frame_rows[index].groups[0];*y=frame_rows[index].groups[1];*z=frame_rows[index].groups[2];(*step)++;
}
/* Use the device's actual typed-texture capabilities, not an SDR/HDR list.
 * The SDK's final synthesis shader already writes float4 to this UAV. */
static int frame_format_supported(DXGI_FORMAT format){
 D3D12_FEATURE_DATA_FORMAT_SUPPORT support={.Format=format};
 return SUCCEEDED(ID3D12Device_CheckFeatureSupport(frame_device,D3D12_FEATURE_FORMAT_SUPPORT,&support,sizeof(support)))&&
  (support.Support1&D3D12_FORMAT_SUPPORT1_TEXTURE2D)&&(support.Support1&D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE)&&
  (support.Support2&D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE);
}
/* Outputs XeFG has released (this reference is the last) and intermediates no output uses any more. XeFG releases a
 * buffer only after its command lists, which carry the copies and enlargements recorded here, have completed. */
static void frame_prune(void){
 UINT kept=0;
 for(UINT i=0;i<frame_output_count;i++){
  ID3D12Resource_AddRef(frame_outputs[i].r);
  if(ID3D12Resource_Release(frame_outputs[i].r)==1){if(frame_outputs[i].heap)ID3D12DescriptorHeap_Release(frame_outputs[i].heap);ID3D12Resource_Release(frame_outputs[i].r);}
  else frame_outputs[kept++]=frame_outputs[i];
 }
 memset(frame_outputs+kept,0,(frame_output_count-kept)*sizeof(*frame_outputs));frame_output_count=kept;
 for(UINT t=0;t<4;t++){
  if(!frame_temps[t].r||frame_temps[t].r==frame_temp)continue;
  UINT used=0;for(UINT i=0;i<frame_output_count;i++)used|=frame_outputs[i].temp==t;
  if(!used){ID3D12Resource_Release(frame_temps[t].r);memset(&frame_temps[t],0,sizeof(frame_temps[t]));}
 }
}
static void frame_initialize_output(DXGI_FORMAT format,UINT width,UINT height){
 for(UINT t=0;t<4;t++)if(frame_temps[t].r&&frame_temps[t].format==format&&frame_temps[t].w==width&&frame_temps[t].h==height){
  frame_temp_index=t;frame_temp=frame_temps[t].r;frame_format=format;frame_temp_w=width;frame_temp_h=height;return;
 }
 if(!frame_format_supported(format))model_fail("generated texture lacks sampling or typed-store support");
 if(!frame_upscale){
  const char*root_name="frame-upsample.rs";
  UINT size;void*blob=graph_blob(root_name,&size);HR(model_create_root_original(frame_device,0,blob,size,&IID_ID3D12RootSignature,(void**)&frame_root));free(blob);
  const char*upscale_name="frame-upsample.dxil";
  blob=graph_blob(upscale_name,&size);D3D12_COMPUTE_PIPELINE_STATE_DESC pd={.pRootSignature=frame_root,.CS={blob,size}};HR(compute_original(frame_device,&pd,&IID_ID3D12PipelineState,(void**)&frame_upscale));free(blob);
 }
 if(frame_temp){
  frame_prune();  /* a new size or format within this context: drop what the old one left */
  char line[160];snprintf(line,sizeof(line),"FRAME_CAP output changed within the context: format=%u generated=%ux%u\n",(UINT)format,width,height);logline(line);
 }
 UINT slot=4;for(UINT t=0;t<4&&slot==4;t++)if(!frame_temps[t].r)slot=t;
 if(slot==4)model_fail("too many generated-frame sizes and formats in one context");
 D3D12_HEAP_PROPERTIES hp={.Type=D3D12_HEAP_TYPE_DEFAULT};D3D12_RESOURCE_DESC rd={.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D,.Width=width,.Height=height,.DepthOrArraySize=1,.MipLevels=1,.Format=format,.SampleDesc={1,0}};
 D3D12_RESOURCE_STATES initial=D3D12_RESOURCE_STATE_COPY_DEST;
 HR(model_committed_original(frame_device,&hp,0,&rd,initial,NULL,&IID_ID3D12Resource,(void**)&frame_temps[slot].r));
 frame_temps[slot].format=format;frame_temps[slot].w=width;frame_temps[slot].h=height;
 frame_temp_index=slot;frame_temp=frame_temps[slot].r;frame_format=format;frame_temp_w=width;frame_temp_h=height;
}
static void frame_finish_dispatch(ID3D12GraphicsCommandList*l,uint64_t shader){
 if(!flow_cap_enabled||!frame_final_shader(shader))return;
 AcquireSRWLockExclusive(&flow_lock);UINT fl=flow_slot(l),active=flow_lists[fl].active;UINT c[18];ID3D12RootSignature*root=flow_lists[fl].root;memcpy(c,flow_lists[fl].values[8],sizeof(c));if(active&&flow_lists[fl].step!=
 44&&flow_lists[fl].step!=60&&flow_lists[fl].step!=FLOW_END
 ){model_fail("incomplete full-frame synthesis");}
 ReleaseSRWLockExclusive(&flow_lock);if(!active)return;
 AcquireSRWLockExclusive(&frame_lock);UINT li=frame_list(l);if((frame_lists[li].table_mask&255)!=255||!frame_lists[li].heap_count)model_fail("incomplete final descriptor tables");UINT64 gpu=frame_lists[li].table[2];SIZE_T cpu=0;
 AcquireSRWLockShared(&model_lock);for(UINT h=0;h<model_heap_count;h++){UINT64 b=model_heaps[h].gpu,n=(UINT64)model_heaps[h].count*model_heaps[h].stride;if(gpu>=b&&gpu-b<n&&(gpu-b)%model_heaps[h].stride==0){cpu=model_heaps[h].cpu+(SIZE_T)(gpu-b);break;}}ReleaseSRWLockShared(&model_lock);
 if(!cpu)model_fail("final output descriptor outside SDK heap");UINT di=frame_desc(cpu);if(!frame_descs[di].valid)model_fail("missing final output UAV");ID3D12Resource*out=frame_descs[di].r;D3D12_RESOURCE_DESC rd=ID3D12Resource_GetDesc(out);D3D12_UNORDERED_ACCESS_VIEW_DESC ud=frame_descs[di].desc;

 UINT output_w=mfg_output_w,output_h=mfg_output_h,cap_w=mfg_cap_w,cap_h=mfg_cap_h;
 if(rd.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||rd.Width!=output_w||rd.Height!=output_h||rd.DepthOrArraySize!=1||rd.MipLevels!=1||rd.SampleDesc.Count!=1||rd.Format!=ud.Format)model_fail("final generated buffer geometry");frame_initialize_output(rd.Format,cap_w,cap_h);
 UINT oi;for(oi=0;oi<frame_output_count;oi++)if(frame_outputs[oi].r==out)break;
 /* A buffer keeps its size and format; settings are read once per process. */
 if(oi<frame_output_count&&frame_outputs[oi].temp!=frame_temp_index)model_fail("generated buffer changed format or size");
 if(oi==frame_output_count&&oi==64){frame_prune();oi=frame_output_count;}
 UINT stride=ID3D12Device_GetDescriptorHandleIncrementSize(frame_device,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 if(oi==frame_output_count){if(oi==64)model_fail("too many generated buffers");frame_output_count++;frame_outputs[oi].r=out;frame_outputs[oi].temp=frame_temp_index;ID3D12Resource_AddRef(out);D3D12_DESCRIPTOR_HEAP_DESC hd={.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,.NumDescriptors=2,.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE};HR(model_heap_original(frame_device,&hd,&IID_ID3D12DescriptorHeap,(void**)&frame_outputs[oi].heap));D3D12_CPU_DESCRIPTOR_HANDLE h=ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(frame_outputs[oi].heap);D3D12_SHADER_RESOURCE_VIEW_DESC sd={.Format=rd.Format,.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D,.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING,.Texture2D={.MipLevels=1}};model_srv_original(frame_device,frame_temp,&sd,h);h.ptr+=stride;frame_uav_original(frame_device,out,NULL,&ud,h);}
 AcquireSRWLockExclusive(&graph_lock);UINT known=0;for(UINT j=0;j<graph_list_count;j++)known|=graph_lists[j]==l;if(!known){if(graph_list_count==128)model_fail("frame queue ownership capacity");graph_lists[graph_list_count++]=l;}ReleaseSRWLockExclusive(&graph_lock);
 D3D12_TEXTURE_COPY_LOCATION src={.pResource=out,.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX},dst={.pResource=frame_temp,.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
 D3D12_GPU_DESCRIPTOR_HANDLE h;
 transition(l,out,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);D3D12_BOX region={0,0,0,cap_w,cap_h,1};ID3D12GraphicsCommandList_CopyTextureRegion(l,&dst,0,0,0,&src,&region);transition(l,out,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);transition(l,frame_temp,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
 ID3D12DescriptorHeap*heap=frame_outputs[oi].heap;frame_heaps_original(l,1,&heap);flow_root_original(l,frame_root);h=ID3D12DescriptorHeap_GetGPUDescriptorHandleForHeapStart(heap);frame_table_original(l,0,h);h.ptr+=stride;frame_table_original(l,1,h);set_original(l,frame_upscale);
 dispatch_original(l,(output_w+7)/8,(output_h+7)/8,1);
 transition(l,frame_temp,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST);
 if(env_uint("XEFG_FRAME_DUMP",0)){
  if(rd.Format!=DXGI_FORMAT_R8G8B8A8_UNORM)model_fail("frame readback format");if(!frame_readback){ID3D12Device_GetCopyableFootprints(frame_device,&rd,0,1,0,&frame_footprint,NULL,NULL,&frame_readback_size);frame_readback=buffer(frame_device,frame_readback_size,D3D12_HEAP_TYPE_READBACK);}
  transition(l,out,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);src.pResource=out;dst.pResource=frame_readback;dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=frame_footprint;ID3D12GraphicsCommandList_CopyTextureRegion(l,&dst,0,0,0,&src,NULL);transition(l,out,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 }
 frame_heaps_original(l,frame_lists[li].heap_count,frame_lists[li].heaps);flow_root_original(l,root);for(UINT j=0;j<8;j++){h.ptr=frame_lists[li].table[j];frame_table_original(l,j,h);}flow_constants_original(l,8,18,c,0);for(UINT j=0;j<nbinding;j++)if(bindings[j].l==l)set_original(l,bindings[j].p);
 frame_completed++;
 if(frame_completed%600==0){char line[120];snprintf(line,sizeof(line),"FRAME_CAP completed=%llu outputs=%u\n",(unsigned long long)frame_completed,frame_output_count);logline(line);}
 ReleaseSRWLockExclusive(&frame_lock);
}
static void frame_report(void){
 char line[160];snprintf(line,sizeof(line),"FRAME_CAP completed=%llu outputs=%u\n",(unsigned long long)frame_completed,frame_output_count);logline(line);
 if(frame_readback){if(!graph_queue)model_fail("missing frame queue fence");ID3D12Fence*f;HR(ID3D12Device_CreateFence(frame_device,0,0,&IID_ID3D12Fence,(void**)&f));HANDLE e=CreateEventA(NULL,0,0,NULL);HR(ID3D12CommandQueue_Signal(graph_queue,f,1));HR(ID3D12Fence_SetEventOnCompletion(f,1,e));if(WaitForSingleObject(e,30000)!=WAIT_OBJECT_0)model_fail("frame readback fence");void*data;HR(ID3D12Resource_Map(frame_readback,0,NULL,&data));save("frame-cap-output.bin",data,(size_t)frame_readback_size);ID3D12Resource_Unmap(frame_readback,0,NULL);ID3D12Fence_Release(f);CloseHandle(e);}
}
static void frame_release_output_views(void){
 for(UINT i=0;i<frame_output_count;i++){if(frame_outputs[i].heap)ID3D12DescriptorHeap_Release(frame_outputs[i].heap);ID3D12Resource_Release(frame_outputs[i].r);}
 memset(frame_outputs,0,sizeof(frame_outputs));frame_output_count=0;
}
static void frame_release(void){
 mfg_profile_checked=mfg_profile_general=0;mfg_second_phase_pending=0;mfg_output_w=mfg_output_h=mfg_cap_w=mfg_cap_h=0;
 for(UINT i=0;i<frame_pso_count;i++)ID3D12PipelineState_Release(frame_psos[i].scaled);
 frame_release_output_views();
 for(UINT t=0;t<4;t++)if(frame_temps[t].r)ID3D12Resource_Release(frame_temps[t].r);memset(frame_temps,0,sizeof(frame_temps));frame_temp_index=0;if(frame_readback)ID3D12Resource_Release(frame_readback);if(frame_root)ID3D12RootSignature_Release(frame_root);if(frame_upscale)ID3D12PipelineState_Release(frame_upscale);
 frame_temp=frame_readback=NULL;frame_root=NULL;frame_upscale=NULL;frame_completed=0;frame_output_count=frame_pso_count=frame_desc_count=frame_list_count=0;memset(frame_lists,0,sizeof(frame_lists));memset(frame_descs,0,sizeof(frame_descs));
}
