/* SPDX-License-Identifier: MIT
 * Private pinned-SDK experiment. All helper dispatches remain inside the
 * original dispatch's GPU interval. One guarded queue owns shared scratch. */
#include "winograd_geometry.h"
_Static_assert(D3D12_CS_DISPATCH_MAX_THREAD_GROUPS_PER_DIMENSION==65535,"dispatch bound");
_Static_assert(D3D12_REQ_BUFFER_RESOURCE_TEXEL_COUNT_2_TO_EXP==27,"buffer bound");
_Static_assert(D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION==16384,"texture bound");
static UINT graph_enabled,graph_ready,graph_adaptive,graph_coarse17;
static UINT graph_refine_columns=48,graph_refine_pad;
/* Fused exact F(2x2,3x3) refinement (wino-ref64.required): one dispatch per 64->64 refinement instead of the
 * prepare/matmul/finish graph. Clamp 16 = 558c3931, 17 = 08155f47/990b9bf8, 18 = 44702172.
 * XEFG_REF64_GX16 (the multi-frame proxy since FreeFG 1.1.2; release/intel_free_mfg.json): its profile's wino-ref64 kernels
 * are compiled with GX=16 and ACC_SHR=1 (src/kernels/wino_ref64.hlsl; release/profile-mfg): 32 x 4 px groups (16 x 2 tiles
 * per role) dispatched over the output size, ((w + 31) / 32, (h + 3) / 4, 2), and acc >> 2 for acc / 4. Both are exact
 * (the kernel bounds its loads by c0.zw and its stores by c1.xy; acc = 4 x conv exactly), so the outputs are the 16 x 8 px
 * form's for every input the owner accepts. */
static UINT graph_ref64;static ID3D12PipelineState*graph_ref64_pso[3];static UINT64 graph_ref64_counts[3];
static ID3D12Device*graph_device;
static ID3D12RootSignature*graph_root;
static ID3D12PipelineState*graph_prepare[3],*graph_multiply[3],*graph_finish[4];
static ID3D12PipelineState*graph_finish_coarse17[2];
static ID3D12PipelineState*graph_finish_mfg[5];
static ID3D12Resource*graph_input[2],*graph_output[2],*graph_retired[32];
static UINT64 graph_capacity[2];static UINT graph_retired_count;
static ID3D12GraphicsCommandList*graph_lists[128];static UINT graph_list_count;
static ID3D12CommandQueue*graph_queue;
static UINT64 graph_counts[7],graph_profiles[3],graph_coarse17_profiles[2];static UINT graph_logged;
static UINT64 graph_geometry_fallbacks;
static SRWLOCK graph_lock=SRWLOCK_INIT;
static void(STDMETHODCALLTYPE*graph_execute_original)(ID3D12CommandQueue*,UINT,ID3D12CommandList*const*);
static void STDMETHODCALLTYPE graph_execute_hook(ID3D12CommandQueue*q,UINT count,ID3D12CommandList*const*lists){
 AcquireSRWLockExclusive(&graph_lock);UINT used=0;
 for(UINT n=0;n<count;n++)for(UINT i=0;i<graph_list_count;i++)if(lists[n]==(ID3D12CommandList*)graph_lists[i])used=1;
 if(used){
  if(graph_queue&&graph_queue!=q)model_fail("Winograd scratch submitted on multiple queues");
  if(!graph_queue){graph_queue=q;ID3D12CommandQueue_AddRef(q);logline("WINOGRAD_QUEUE single submission owner established\n");}
 }
 ReleaseSRWLockExclusive(&graph_lock);
 if(scale_queue_execute(q,count,lists,graph_execute_original))return;
 graph_execute_original(q,count,lists);
}
static void*graph_blob(const char*name,UINT*size){
 char path[1400];snprintf(path,sizeof(path),"%s\\%s",patchdir,name);FILE*f=fopen(path,"rb");if(!f)model_fail("missing Winograd helper");
 if(fseek(f,0,SEEK_END))model_fail("Winograd helper seek");long length=ftell(f);if(length<=0||length>8*1024*1024)model_fail("Winograd helper size");rewind(f);
 void*bytes=malloc((size_t)length);if(!bytes||fread(bytes,1,(size_t)length,f)!=(size_t)length)model_fail("Winograd helper read");fclose(f);*size=(UINT)length;
 char line[160];snprintf(line,sizeof(line),"WINOGRAD_HELPER name=%s hash=%016llx\n",name,(unsigned long long)hash(bytes,*size));logline(line);return bytes;
}
static ID3D12PipelineState*graph_pipeline(const char*name){
 UINT size;void*bytes=graph_blob(name,&size);D3D12_COMPUTE_PIPELINE_STATE_DESC d={.pRootSignature=graph_root,.CS={bytes,size}};ID3D12PipelineState*p;
 HR(compute_original(graph_device,&d,&IID_ID3D12PipelineState,(void**)&p));free(bytes);return p;
}
static ID3D12Resource*graph_buffer(UINT64 bytes){
 D3D12_HEAP_PROPERTIES hp={.Type=D3D12_HEAP_TYPE_DEFAULT,.CreationNodeMask=1,.VisibleNodeMask=1};
 D3D12_RESOURCE_DESC rd={.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER,.Width=bytes,.Height=1,.DepthOrArraySize=1,.MipLevels=1,.SampleDesc={1,0},.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR,.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS};
 ID3D12Resource*r;HR(model_committed_original(graph_device,&hp,0,&rd,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,NULL,&IID_ID3D12Resource,(void**)&r));return r;
}
static void graph_initialize(void){
 if(!graph_enabled)return;
 for(UINT i=0;i<model_root_count;i++)if(model_graph_roots[i]){graph_root=model_roots[i];break;}
 if(!graph_root)model_fail("no expanded Winograd root");
 if(graph_enabled&1){graph_prepare[0]=graph_pipeline("graph-prepare224.dxil");graph_multiply[0]=graph_pipeline("graph-matmul224.dxil");graph_finish[0]=graph_pipeline("graph-finish224.dxil");}
 if(graph_enabled&2){graph_prepare[1]=graph_pipeline("graph-prepare64.dxil");graph_multiply[1]=graph_pipeline("graph-matmul64.dxil");graph_finish[1]=graph_pipeline("graph-finish64-16.dxil");graph_finish[2]=graph_pipeline("graph-finish64-17.dxil");}
 if(graph_adaptive){graph_prepare[2]=graph_pipeline("graph-prepare224-n32.dxil");graph_multiply[2]=graph_pipeline("graph-matmul224-n32.dxil");graph_finish[3]=graph_pipeline("graph-finish224-n32.dxil");}
 if(graph_coarse17){graph_finish_coarse17[0]=graph_pipeline("graph-finish224-17.dxil");if(graph_adaptive)graph_finish_coarse17[1]=graph_pipeline("graph-finish224-17-n32.dxil");}
 graph_finish_mfg[0]=graph_pipeline("mfg-finish224-18-n48.dxil");graph_finish_mfg[1]=graph_pipeline("mfg-finish224-18-n32.dxil");
 graph_finish_mfg[2]=graph_pipeline("mfg-finish224-19-n48.dxil");graph_finish_mfg[3]=graph_pipeline("mfg-finish224-19-n32.dxil");
 graph_finish_mfg[4]=graph_pipeline("mfg-finish64-18-n32.dxil");
 if(graph_ref64){graph_ref64_pso[0]=graph_pipeline("wino-ref64-16.dxil");graph_ref64_pso[1]=graph_pipeline("wino-ref64-17.dxil");graph_ref64_pso[2]=graph_pipeline("wino-ref64-18.dxil");}
 graph_ready=1;logline("WINOGRAD_READY U24/F4 M32 prep8 finish32\n");
}
static void install_graph(ID3D12Device*d,ID3D12CommandQueue*q){
 graph_enabled=env_uint("XEFG_WINOGRAD",0);
 if(*patchdir){char path[1400];snprintf(path,sizeof(path),"%s\\winograd.required",patchdir);FILE*f=fopen(path,"r");if(f){int required=fgetc(f)-'0';fclose(f);if(required<1||required>3||graph_enabled!=(UINT)required)model_fail("Winograd helper mask required by candidate");}}
 if(!graph_enabled)return;
 if(graph_enabled>3||model_owner_enabled!=7||!*patchdir)model_fail("Winograd requires mode7 and paired helpers");
 char path[1400];snprintf(path,sizeof(path),"%s\\winograd-adaptive.required",patchdir);FILE*f=fopen(path,"r");if(f){int enabled=fgetc(f);fclose(f);if(enabled!='1'||!(graph_enabled&1))model_fail("invalid adaptive Winograd profile");graph_adaptive=1;}
 snprintf(path,sizeof(path),"%s\\winograd-coarse17.required",patchdir);f=fopen(path,"r");if(f){int enabled=fgetc(f);fclose(f);if(enabled!='1'||!(graph_enabled&1))model_fail("invalid coarse17 Winograd profile");graph_coarse17=1;}
 snprintf(path,sizeof(path),"%s\\winograd-refine-pitch.required",patchdir);f=fopen(path,"r");if(f){unsigned columns,pad;char extra;int fields=fscanf(f,"%u %u %c",&columns,&pad,&extra);fclose(f);if(fields!=2||columns!=32||pad!=16||!(graph_enabled&2))model_fail("invalid refinement pitch profile");graph_refine_columns=columns;graph_refine_pad=pad;}
 snprintf(path,sizeof(path),"%s\\wino-ref64.required",patchdir);f=fopen(path,"r");
 if(f){int enabled=fgetc(f);fclose(f);
  /* The kernel reads the conv64 segment (bit 128) and sums all 64 channels in FP32 (bit 256 proofs). */
  if(enabled!='1'||!(graph_enabled&2)||(model_wino_enc16&384)!=384)model_fail("invalid fused refinement profile");
  graph_ref64=1;logline("WINO_REF64 fused exact refinement enabled\n");logline("WINO_REF64_GROUPS 32x4 px over the output size, acc>>2\n");
 }
 graph_device=d;graph_execute_original=q->lpVtbl->ExecuteCommandLists;replace((void*)&q->lpVtbl->ExecuteCommandLists,graph_execute_hook);
}
static int graph_dispatch(ID3D12GraphicsCommandList*l,uint64_t shader,UINT x,UINT y,UINT z){
 UINT family,kind;
 if(shader==0xfec421a3b6a0632bULL){family=0;kind=0;}else if(shader==0x558c3931ba6fb064ULL){family=1;kind=1;}else if(shader==0x08155f47bc92811bULL){family=1;kind=2;}else if(shader==0x18a0d2663b5d5282ULL&&graph_coarse17){family=0;kind=3;}
 else if(shader==0x3c5180037dafdbb8ULL){family=0;kind=4;}
 else if(shader==0x8b17a4f9fcb35e18ULL){family=0;kind=5;}
 else if(shader==0x990b9bf8cf279d27ULL){family=1;kind=2;}
 else if(shader==0x4470217240e7372aULL){family=1;kind=6;}
 else return 0;
 if(!(graph_enabled&(1u<<family)))return 0;if(!graph_ready)model_fail("Winograd dispatched before initialization");
 AcquireSRWLockExclusive(&graph_lock);
 UINT c[12];ID3D12RootSignature*root=NULL;ID3D12PipelineState*original=NULL;
 AcquireSRWLockShared(&model_lock);
 for(UINT i=0;i<model_list_count;i++)if(model_lists[i].l==l){
  if(model_lists[i].constant_mask!=4095||!model_lists[i].table0||!model_lists[i].table)model_fail("incomplete Winograd root arguments");
  root=model_lists[i].root;memcpy(c,model_lists[i].constants,sizeof(c));break;
 }
 UINT compatible=0;for(UINT i=0;i<model_root_count;i++)if(model_roots[i]==root&&model_graph_roots[i])compatible=1;
 ReleaseSRWLockShared(&model_lock);if(!compatible)model_fail("Winograd root was not expanded");
 for(UINT i=0;i<nbinding;i++)if(bindings[i].l==l)original=bindings[i].p;
 if(!original)model_fail("missing original Winograd PSO");
 UINT channels=family?64:224,pack=family?16:8,w=c[4],h=c[5];
 if(!w||!h||x!=((UINT64)w+7)/8||y!=((UINT64)h+7)/8||z!=channels/pack)model_fail("unexpected Winograd dispatch geometry");
 if(family&&graph_ref64){
  /* wino_ref64: 16x8-pixel, 32-channel groups; the kernel bounds its loads (c0.zw) and stores (c1.xy). */
  UINT clamp=kind==1?16:kind==6?18:17;
  set_original(l,graph_ref64_pso[clamp-16]);dispatch_original(l,(w+31)/32,(h+3)/4,2);set_original(l,original);graph_ref64_counts[clamp-16]++;
  if(!(graph_logged&(256u<<kind))){char line[160];snprintf(line,sizeof(line),"WINO_REF64_EXECUTE shader=%016llx clamp=%u\n",(unsigned long long)shader,clamp);logline(line);graph_logged|=256u<<kind;}
  ReleaseSRWLockExclusive(&graph_lock);return 1;
 }
 UINT64 tile_count=(((UINT64)w+3)/4)*(((UINT64)h+3)/4);UINT profile=family;
 if(tile_count>65535){graph_geometry_fallbacks++;ReleaseSRWLockExclusive(&graph_lock);return 0;}
 UINT tiles=(UINT)tile_count;
 if(!family&&graph_adaptive&&((tiles+31)/32)*32<((tiles+47)/48)*48)profile=2;
 UINT columns=family?graph_refine_columns:profile==2?32:48;
 struct bc250_winograd_geometry geometry;
 if(!bc250_winograd_geometry(w,h,channels,columns,family?graph_refine_pad:0,&geometry)){
  /* The owned model retains its original coefficient prefix, and the expanded
   * root retains its first three bindings. The original PSO remains usable. */
  graph_geometry_fallbacks++;ReleaseSRWLockExclusive(&graph_lock);return 0;
 }
 UINT matrix_columns=geometry.matrix_columns,stride=geometry.stride;UINT64 bytes=geometry.bytes;
 if(bytes>graph_capacity[family]){
  if(graph_input[family]){if(graph_retired_count+2>32)model_fail("Winograd scratch growth limit");graph_retired[graph_retired_count++]=graph_input[family];graph_retired[graph_retired_count++]=graph_output[family];}
  graph_input[family]=graph_buffer(bytes);graph_output[family]=graph_buffer(bytes);graph_capacity[family]=bytes;
  char line[160];snprintf(line,sizeof(line),"WINOGRAD_SCRATCH channels=%u bytes_each=%llu\n",channels,(unsigned long long)bytes);logline(line);
 }
 UINT known=0;for(UINT i=0;i<graph_list_count;i++)known|=graph_lists[i]==l;
 if(!known){if(graph_list_count==128)model_fail("Winograd list tracking limit");graph_lists[graph_list_count++]=l;}
 ID3D12GraphicsCommandList_SetComputeRootUnorderedAccessView(l,3,ID3D12Resource_GetGPUVirtualAddress(graph_input[family]));
 ID3D12GraphicsCommandList_SetComputeRootUnorderedAccessView(l,4,ID3D12Resource_GetGPUVirtualAddress(graph_output[family]));
 D3D12_RESOURCE_BARRIER barrier={.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV,.UAV={NULL}};ID3D12GraphicsCommandList_ResourceBarrier(l,1,&barrier);
 set_original(l,graph_prepare[profile]);dispatch_original(l,stride/8,channels/8,1);
 barrier.UAV.pResource=graph_input[family];ID3D12GraphicsCommandList_ResourceBarrier(l,1,&barrier);
 set_original(l,graph_multiply[profile]);dispatch_original(l,matrix_columns/columns,channels/32,36);
 barrier.UAV.pResource=graph_output[family];ID3D12GraphicsCommandList_ResourceBarrier(l,1,&barrier);
 ID3D12PipelineState*finish;
 if(kind>=4)finish=graph_finish_mfg[kind==6?4:(kind-4)*2+(profile==2)];else
 finish=kind==3?graph_finish_coarse17[profile==2]:graph_finish[profile==2?3:kind];
 set_original(l,finish);dispatch_original(l,tiles,channels/32,1);
 // The SDK's expanded signature retains its original first three arguments.
 // Its original shaders do not consume u1/u2; only the PSO changes here.
 set_original(l,original);graph_counts[kind]++;if(kind==3)graph_coarse17_profiles[profile==2]++;else graph_profiles[profile]++;
 if(!(graph_logged&(1u<<kind))){char line[160];snprintf(line,sizeof(line),"WINOGRAD_EXECUTE shader=%016llx channels=%u clamp=%u\n",(unsigned long long)shader,channels,kind==5?19:kind>=4?18:kind>=2?17:16);logline(line);graph_logged|=1u<<kind;}
 ReleaseSRWLockExclusive(&graph_lock);return 1;
}
static void graph_report(void){
 if(graph_enabled){char line[120];snprintf(line,sizeof(line),"WINOGRAD_GEOMETRY fallback=%llu\n",(unsigned long long)graph_geometry_fallbacks);logline(line);}
 if(graph_ref64){char line[160];snprintf(line,sizeof(line),"WINO_REF64 clamp16=%llu clamp17=%llu clamp18=%llu\n",(unsigned long long)graph_ref64_counts[0],(unsigned long long)graph_ref64_counts[1],(unsigned long long)graph_ref64_counts[2]);logline(line);}
 if(graph_enabled){char line[160];snprintf(line,sizeof(line),"MFG_WINOGRAD coarse18=%llu coarse19=%llu refinement18=%llu\n",graph_counts[4],graph_counts[5],graph_counts[6]);logline(line);}
 if(graph_enabled){char line[180];if(graph_refine_pad){snprintf(line,sizeof(line),"WINOGRAD_REFINE_LAYOUT columns=%u pad=%u calls=%llu\n",graph_refine_columns,graph_refine_pad,(unsigned long long)(graph_counts[1]+graph_counts[2]));logline(line);}snprintf(line,sizeof(line),"WINOGRAD_COUNTS coarse=%llu refinement16=%llu refinement17=%llu\n",(unsigned long long)graph_counts[0],(unsigned long long)graph_counts[1],(unsigned long long)graph_counts[2]);logline(line);snprintf(line,sizeof(line),"WINOGRAD_PROFILES coarse48=%llu refinement=%llu coarse32=%llu\n",(unsigned long long)graph_profiles[0],(unsigned long long)graph_profiles[1],(unsigned long long)graph_profiles[2]);logline(line);if(graph_coarse17){snprintf(line,sizeof(line),"WINOGRAD_COARSE17 count=%llu columns48=%llu columns32=%llu\n",(unsigned long long)graph_counts[3],(unsigned long long)graph_coarse17_profiles[0],(unsigned long long)graph_coarse17_profiles[1]);logline(line);}}}
