/* SPDX-License-Identifier: MIT
 * CPU-only unit test of F4Q (src/model_f4q.h, src/game/f4q.h) in the multi-frame proxy, run under Wine by
 * release/check_proxy_wine.py --variant intel-free-mfg (its "f4q" cases). It includes those headers and the real
 * settings reader (src/game/mfg_settings.h) with stand-ins for the rest of the add-on: mock D3D12 objects (own vtables,
 * fake resources, heaps and a fake readback); only the root signature serializer and deserializer come from Wine's
 * d3d12.dll. No device, no GPU.
 *
 *   test_f4q.exe MODE DIR      DIR: a scratch shader folder; the settings file is BC250-XeFG\settings.ini beside the
 *                              program, which check_proxy_wine.py writes per case
 * MODE (the environment is set here):
 *   switch     BC250_XEFG_F4Q, BC250_XEFG_F4Q2, BC250_XEFG_EXACT and BC250_XEFG_F4Q_SHADOW as the case sets them; prints
 *              the configuration, the segment sizes (SEGMENT, SEGMENT2 for F4Q2's 18432- and 73728-byte models, SEGMENT3
 *              for the FP16 forms' copies of every size), the pipelines compute_hook creates for b3941ac8, f030948d,
 *              the F4Q2 layers 1a3b0782 (named "other": a F(2x2) shader whenever F4Q2 is off), e83e868f and 9e0080ee,
 *              the row layers 60edebbb and b3ddf030, the F(2x2) layers 1f27b449, f2e2e13f, 5654aa38 and 4bb52a63, and a
 *              shader that is never a target, each one's dispatch geometry, and whether the check installed any hook
 *   fallback   F4Q on (the case sets BC250_XEFG_EXACT=1); b3941ac8's F(4x4) pipeline cannot be created and f030948d's
 *              F(4x4) file is missing: both fall back to the F(2x2) file and geometry
 *   fp16fallback  F4Q and the FP16 forms on; the FP16 files of e83e868f (FP16 table in place), 1a3b0782 (FP16 copy) and
 *              1f27b449 (packed FP16) are missing and f2e2e13f's FP16 pipeline cannot be created
 *   layout     F4Q on, but the profile's enc16 marker lacks the row16 segment, so the segment offsets are not the
 *              kernels': F4Q stays off
 *   layout2    as switch, but the marker lacks the 18432- and 73728-byte layouts: F4Q2's e83e868f and 9e0080ee stay off
 *   shadow     BC250_XEFG_F4Q_SHADOW=1: the check's sequence at every target dispatch, with F4Q2 on also at its three
 *              layers (points 3..5)
 *   pack       F4Q on (the case sets BC250_XEFG_EXACT=1: FP32 tables): the model owner's segment of one 2304- and one
 *              4608-byte model (with F4Q2 on also one 18432- and one 73728-byte model) against an independent computation
 * Output: the fast-log lines of F4Q, plus test lines (CONFIG, SEGMENT, PSO, GEOM, VTABLE, OWN, INTEL, REFS, TOTALS, PACK)
 * and DONE. check_proxy_wine.py checks them.
 */
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
int _fltused;
static HANDLE out;
static void logline(const char*s){DWORD n;WriteFile(out,s,(DWORD)strlen(s),&n,NULL);}
static void proxy_log(const char*s){logline(s);}
#include "mfg_settings.h"   /* the real settings reader: the F4Q key of BC250-XeFG\settings.ini */
static void replace(void*slot,void*p){memcpy(slot,&p,sizeof(p));}
static char patchdir[1024];
static struct{ID3D12GraphicsCommandList*l;ID3D12PipelineState*p;} bindings[8];static UINT nbinding;
static void model_fail(const char*w){char line[200];snprintf(line,sizeof(line),"MODEL_FAIL %s\n",w);logline(line);ExitProcess(4);}
/* the model owner's layout for the profile's marker (1535 = the release marker; owner 7): 2304- and 4608-byte models */
static UINT model_wino_enc16=1535;
static UINT model_enc16_layout(UINT bytes,UINT*cin_slices){   /* src/model_wino_enc16.h's sizes */
 UINT bit=bytes==2304?1:bytes==4608?2:bytes==18432?4:bytes==9216?8:bytes==73728?16:bytes==36864?32:0;
 if(!(model_wino_enc16&bit))return 0;
 *cin_slices=bytes==18432||bytes==9216?2:bytes==73728||bytes==36864?4:1;return bytes/2304;
}
/* the owner's real offsets for every size, the 36864-byte models included (base 7x + the flow-graph segment, the conv64
 * segment and its FP16 copy), so the FP16 forms' layout check sees the add-on's layout */
static UINT model_enc16_offset(UINT bytes){return bytes==36864?bytes*7u+64u*64u*81u:bytes*5;}
static UINT model_row16_size(UINT bytes){return (model_wino_enc16&64)&&((bytes==2304&&model_wino_enc16&1)||(bytes==4608&&model_wino_enc16&2))?bytes/2304*12288u:0;}
static UINT model_ref64_size(UINT bytes){return (model_wino_enc16&128)&&bytes==36864?16*16384u+16u:0;}
static UINT model_f16_size(UINT bytes){UINT cs;UINT chunks=model_enc16_layout(bytes,&cs);if(!(model_wino_enc16&1024)||!chunks)return 0;return chunks*8192u+(model_ref64_size(bytes)?16*8192u:0);}
/* the model owner's innermost entries: absent in this test (the hooks then call the next entry) */
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateCommittedResource) model_committed_original;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateRootSignature) model_create_root_original;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateDescriptorHeap) model_heap_original;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateUnorderedAccessView) model_uav_original;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateShaderResourceView) model_srv_original;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRootSignature) model_root_original;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRootDescriptorTable) model_table_original;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRoot32BitConstants) model_constants_original;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->CopyBufferRegion) model_copy_original;
static ID3D12Resource*test_model;
#define FQ_MODEL_COUNT() (1u)
#define FQ_MODEL_R(i) (test_model)
static HRESULT(STDMETHODCALLTYPE*compute_original)(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,REFIID,void**);
static void(STDMETHODCALLTYPE*set_original)(ID3D12GraphicsCommandList*,ID3D12PipelineState*);
static void(STDMETHODCALLTYPE*dispatch_original)(ID3D12GraphicsCommandList*,UINT,UINT,UINT);
static int profile_lists_replacement(uint64_t s){(void)s;return 1;}   /* every profile file is listed here */
#include "model_f4q.h"
#include "f4q.h"
/* src/model_wino_enc16.h's FP16 of an integer |v| < 2048 (the FP16 forms' copies) */
static uint16_t model_half_int(int v){UINT mag=v<0?(UINT)-v:(UINT)v;if(!mag)return 0;if(mag>=2048)model_fail("FP16 Winograd coefficient range");UINT e=0;while((1u<<(e+1))<=mag)e++;return (uint16_t)((v<0?0x8000u:0)|((e+15)<<10)|((mag-(1u<<e))<<(10-e)));}

/* ---- generic refcounted mock objects */
struct mobj { const void*vtbl; LONG refs; char name[48]; };
static ULONG STDMETHODCALLTYPE m_addref(void*This){return (ULONG)InterlockedIncrement(&((struct mobj*)This)->refs);}
static ULONG STDMETHODCALLTYPE m_release(void*This){return (ULONG)InterlockedDecrement(&((struct mobj*)This)->refs);}
struct mres { ID3D12Resource iface; LONG refs; char name[48]; D3D12_RESOURCE_DESC d; UINT64 va; void*mem; };
static D3D12_RESOURCE_DESC* STDMETHODCALLTYPE mres_desc(ID3D12Resource*This,D3D12_RESOURCE_DESC*ret){*ret=((struct mres*)This)->d;return ret;}
static D3D12_GPU_VIRTUAL_ADDRESS STDMETHODCALLTYPE mres_va(ID3D12Resource*This){return ((struct mres*)This)->va;}
static HRESULT STDMETHODCALLTYPE mres_map(ID3D12Resource*This,UINT sub,const D3D12_RANGE*r,void**p){(void)sub;(void)r;struct mres*m=(void*)This;if(!m->mem)m->mem=calloc(1,(size_t)m->d.Width);*p=m->mem;return S_OK;}
static void STDMETHODCALLTYPE mres_unmap(ID3D12Resource*This,UINT sub,const D3D12_RANGE*r){(void)This;(void)sub;(void)r;}
static ID3D12ResourceVtbl mres_vtbl;
static struct mres*res_all[64];static UINT res_count;
static struct mres*tex(const char*name,UINT64 w,UINT h,UINT16 z,DXGI_FORMAT f,int uav){
 struct mres*r=calloc(1,sizeof(*r));r->iface.lpVtbl=&mres_vtbl;r->refs=1;snprintf(r->name,sizeof(r->name),"%s",name);
 r->d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;r->d.Width=w;r->d.Height=h;r->d.DepthOrArraySize=z;r->d.MipLevels=1;r->d.Format=f;r->d.SampleDesc.Count=1;
 r->d.Flags=uav?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:0;res_all[res_count++]=r;return r;
}
static struct mres*buf(const char*name,UINT64 bytes){
 struct mres*r=calloc(1,sizeof(*r));r->iface.lpVtbl=&mres_vtbl;r->refs=1;snprintf(r->name,sizeof(r->name),"%s",name);
 r->d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;r->d.Width=bytes;r->d.Height=1;r->d.DepthOrArraySize=1;r->d.MipLevels=1;r->d.SampleDesc.Count=1;
 r->d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;r->va=0x5000000000ull+0x10000000ull*res_count;res_all[res_count++]=r;return r;
}
static const char*res_name(ID3D12Resource*r){for(UINT i=0;i<res_count;i++)if(&res_all[i]->iface==r)return res_all[i]->name;return r?"?":"null";}
struct mheap { ID3D12DescriptorHeap iface; LONG refs; char name[48]; SIZE_T cpu; UINT64 gpu; UINT count; };
static D3D12_CPU_DESCRIPTOR_HANDLE* STDMETHODCALLTYPE mheap_cpu(ID3D12DescriptorHeap*This,D3D12_CPU_DESCRIPTOR_HANDLE*ret){ret->ptr=((struct mheap*)This)->cpu;return ret;}
static D3D12_GPU_DESCRIPTOR_HANDLE* STDMETHODCALLTYPE mheap_gpu(ID3D12DescriptorHeap*This,D3D12_GPU_DESCRIPTOR_HANDLE*ret){ret->ptr=((struct mheap*)This)->gpu;return ret;}
static ID3D12DescriptorHeapVtbl mheap_vtbl;
static UINT heap_seq;static struct mheap*heaps_all[8];
static ID3D12RootSignatureVtbl mroot_vtbl;static ID3D12PipelineStateVtbl mpso_vtbl;
static struct mobj*roots_all[16];static UINT root_count;static struct mobj*psos_all[32];static UINT pso_count;
static struct mobj*mk(const void*vtbl,const char*name){struct mobj*o=calloc(1,sizeof(*o));o->vtbl=vtbl;o->refs=1;snprintf(o->name,sizeof(o->name),"%s",name);return o;}

/* ---- mock device */
static HRESULT STDMETHODCALLTYPE d_root(ID3D12Device*d,UINT node,const void*data,SIZE_T size,REFIID iid,void**o){(void)d;(void)node;(void)data;(void)size;(void)iid;
 char n[16];snprintf(n,sizeof(n),"root%u",root_count);roots_all[root_count]=mk(&mroot_vtbl,n);*o=roots_all[root_count++];return S_OK;}
static int own_heap_cpu(SIZE_T cpu){for(UINT i=0;i<heap_seq;i++)if(!strcmp(heaps_all[i]->name,"own")&&cpu>=heaps_all[i]->cpu&&cpu<heaps_all[i]->cpu+heaps_all[i]->count*32)return (int)((cpu-heaps_all[i]->cpu)/32);return -1;}
static void STDMETHODCALLTYPE d_uav(ID3D12Device*d,ID3D12Resource*r,ID3D12Resource*c,const D3D12_UNORDERED_ACCESS_VIEW_DESC*x,D3D12_CPU_DESCRIPTOR_HANDLE h){(void)d;(void)c;
 int i=own_heap_cpu(h.ptr);if(i<0)return;char line[220];
 if(x->ViewDimension==D3D12_UAV_DIMENSION_BUFFER)snprintf(line,sizeof(line),"VIEW own=%d uav res=%s buffer num=%u\n",i,res_name(r),x->Buffer.NumElements);
 else snprintf(line,sizeof(line),"VIEW own=%d uav res=%s dim=%u fmt=%u first=%u size=%u\n",i,res_name(r),x->ViewDimension,x->Format,x->Texture2DArray.FirstArraySlice,x->Texture2DArray.ArraySize);
 logline(line);}
static void STDMETHODCALLTYPE d_srv(ID3D12Device*d,ID3D12Resource*r,const D3D12_SHADER_RESOURCE_VIEW_DESC*x,D3D12_CPU_DESCRIPTOR_HANDLE h){(void)d;(void)r;(void)x;(void)h;}
static void STDMETHODCALLTYPE d_cbv(ID3D12Device*d,const D3D12_CONSTANT_BUFFER_VIEW_DESC*x,D3D12_CPU_DESCRIPTOR_HANDLE h){(void)d;(void)x;(void)h;}
static void STDMETHODCALLTYPE d_copy_simple(ID3D12Device*d,UINT n,D3D12_CPU_DESCRIPTOR_HANDLE a,D3D12_CPU_DESCRIPTOR_HANDLE b,D3D12_DESCRIPTOR_HEAP_TYPE t){(void)d;(void)n;(void)a;(void)b;(void)t;}
static void STDMETHODCALLTYPE d_copy(ID3D12Device*d,UINT nd,const D3D12_CPU_DESCRIPTOR_HANDLE*a,const UINT*an,UINT ns,const D3D12_CPU_DESCRIPTOR_HANDLE*b,const UINT*bn,D3D12_DESCRIPTOR_HEAP_TYPE t){(void)d;(void)nd;(void)a;(void)an;(void)ns;(void)b;(void)bn;(void)t;}
static const char*heap_name_next="intel";
static HRESULT STDMETHODCALLTYPE d_heap(ID3D12Device*d,const D3D12_DESCRIPTOR_HEAP_DESC*x,REFIID iid,void**o){
 (void)d;(void)iid;struct mheap*h=calloc(1,sizeof(*h));h->iface.lpVtbl=&mheap_vtbl;h->refs=1;heap_seq++;h->count=x->NumDescriptors;
 snprintf(h->name,sizeof(h->name),"%s",heap_name_next);heap_name_next="own";heaps_all[heap_seq-1]=h;
 h->cpu=0x100000*heap_seq;h->gpu=(x->Flags&D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE)?0x7000000000ull+0x10000000ull*heap_seq:0;*o=h;return S_OK;
}
static UINT STDMETHODCALLTYPE d_inc(ID3D12Device*d,D3D12_DESCRIPTOR_HEAP_TYPE t){(void)d;return t==D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER?16:32;}
static HRESULT STDMETHODCALLTYPE d_committed(ID3D12Device*d,const D3D12_HEAP_PROPERTIES*hp,D3D12_HEAP_FLAGS f,const D3D12_RESOURCE_DESC*rd,D3D12_RESOURCE_STATES s,const D3D12_CLEAR_VALUE*c,REFIID iid,void**o){
 (void)d;(void)f;(void)s;(void)c;(void)iid;char n[48];snprintf(n,sizeof(n),"own-%s-%llu",hp->Type==D3D12_HEAP_TYPE_READBACK?"readback":"default",(unsigned long long)rd->Width);
 struct mres*r=buf(n,rd->Width);*o=&r->iface;return S_OK;}
/* pipeline creation: the pipeline is named after its bytecode (the profile files hold their names as text); a bytecode
 * named in fail_bytecode fails, as a driver that cannot compile it would */
static const char*fail_bytecode;
static HRESULT STDMETHODCALLTYPE m_compute(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*x,REFIID iid,void**o){
 (void)d;(void)iid;char n[48]={0};memcpy(n,x->CS.pShaderBytecode,x->CS.BytecodeLength<47?x->CS.BytecodeLength:47);
 if(fail_bytecode&&!strcmp(n,fail_bytecode)){*o=NULL;return E_INVALIDARG;}
 psos_all[pso_count]=mk(&mpso_vtbl,n);*o=psos_all[pso_count++];return S_OK;}
static ID3D12DeviceVtbl dv;
/* ---- mock list: the state the GPU would see */
static struct { ID3D12RootSignature*root; ID3D12PipelineState*pso; UINT64 tables[16]; UINT c[16][64]; ID3D12DescriptorHeap*heaps[2]; UINT nheaps; UINT64 va[16]; } gpu, want;
static UINT barriers,copies;
static void STDMETHODCALLTYPE l_root(ID3D12GraphicsCommandList*l,ID3D12RootSignature*r){(void)l;if(gpu.root!=r){memset(gpu.tables,0,sizeof(gpu.tables));memset(gpu.c,0,sizeof(gpu.c));memset(gpu.va,0,sizeof(gpu.va));}gpu.root=r;}
static void STDMETHODCALLTYPE l_table(ID3D12GraphicsCommandList*l,UINT i,D3D12_GPU_DESCRIPTOR_HANDLE h){(void)l;gpu.tables[i]=h.ptr;}
static void STDMETHODCALLTYPE l_constant(ID3D12GraphicsCommandList*l,UINT i,UINT v,UINT o){(void)l;gpu.c[i][o]=v;}
static void STDMETHODCALLTYPE l_constants(ID3D12GraphicsCommandList*l,UINT i,UINT n,const void*v,UINT o){(void)l;memcpy(&gpu.c[i][o],v,n*4);}
static void STDMETHODCALLTYPE l_va(ID3D12GraphicsCommandList*l,UINT i,D3D12_GPU_VIRTUAL_ADDRESS a){(void)l;gpu.va[i]=a;}
static void STDMETHODCALLTYPE l_heaps(ID3D12GraphicsCommandList*l,UINT n,ID3D12DescriptorHeap*const*h){(void)l;gpu.nheaps=n;for(UINT i=0;i<n;i++)gpu.heaps[i]=h[i];}
static HRESULT STDMETHODCALLTYPE l_reset(ID3D12GraphicsCommandList*l,ID3D12CommandAllocator*a,ID3D12PipelineState*p){(void)l;(void)a;(void)p;return S_OK;}
static void STDMETHODCALLTYPE l_barrier(ID3D12GraphicsCommandList*l,UINT n,const D3D12_RESOURCE_BARRIER*b){(void)l;(void)b;barriers+=n;}
static void STDMETHODCALLTYPE l_copy(ID3D12GraphicsCommandList*l,ID3D12Resource*dst,UINT64 doff,ID3D12Resource*src,UINT64 soff,UINT64 n){(void)l;
 char line[200];snprintf(line,sizeof(line),"COPY dst=%s+%llu src=%s+%llu bytes=%llu\n",res_name(dst),(unsigned long long)doff,res_name(src),(unsigned long long)soff,(unsigned long long)n);logline(line);copies++;}
static void STDMETHODCALLTYPE m_setpso(ID3D12GraphicsCommandList*l,ID3D12PipelineState*p){(void)l;gpu.pso=p;}
static int rt_state(void){return gpu.root==want.root&&gpu.nheaps==want.nheaps&&gpu.heaps[0]==want.heaps[0]&&!memcmp(gpu.tables,want.tables,sizeof(gpu.tables))&&
                               !memcmp(gpu.c,want.c,sizeof(gpu.c))&&!memcmp(gpu.va,want.va,sizeof(gpu.va));}
static UINT own_dispatches;
static void STDMETHODCALLTYPE m_dispatch(ID3D12GraphicsCommandList*l,UINT x,UINT y,UINT z){(void)l;
 struct mobj*p=(struct mobj*)gpu.pso;char line[400];int u=snprintf(line,sizeof(line),"OWN pso=%s groups=%u,%u,%u heap=%s RT %s c=",p?p->name:"none",x,y,z,
  gpu.nheaps?((struct mheap*)gpu.heaps[0])->name:"none",rt_state()?"ok":"bad");
 for(UINT i=0;i<16;i++)u+=snprintf(line+u,sizeof(line)-u,"%s%u",i?",":"",gpu.c[3][i]);
 u+=snprintf(line+u,sizeof(line)-u," t1=%llx\n",(unsigned long long)gpu.tables[1]);logline(line);own_dispatches++;}
static ID3D12GraphicsCommandListVtbl lv;

static HRESULT(WINAPI*serialize)(const D3D12_VERSIONED_ROOT_SIGNATURE_DESC*,ID3DBlob**,ID3DBlob**);
static ID3D12RootSignature*make_root(ID3D12Device*d,const D3D12_ROOT_SIGNATURE_DESC1*s){
 D3D12_VERSIONED_ROOT_SIGNATURE_DESC v={.Version=D3D_ROOT_SIGNATURE_VERSION_1_1};v.Desc_1_1=*s;ID3DBlob*blob=NULL,*err=NULL;
 if(FAILED(serialize(&v,&blob,&err))){logline("TEST serialize failed\n");ExitProcess(3);}
 ID3D12RootSignature*r=NULL;d->lpVtbl->CreateRootSignature(d,0,ID3D10Blob_GetBufferPointer(blob),ID3D10Blob_GetBufferSize(blob),&IID_ID3D12RootSignature,(void**)&r);
 ID3D10Blob_Release(blob);return r;
}
static D3D12_CPU_DESCRIPTOR_HANDLE C(struct mheap*h,UINT i){D3D12_CPU_DESCRIPTOR_HANDLE x={h->cpu+(SIZE_T)i*32};return x;}
static D3D12_GPU_DESCRIPTOR_HANDLE G(struct mheap*h,UINT i){D3D12_GPU_DESCRIPTOR_HANDLE x={h->gpu+(UINT64)i*32};return x;}
static ID3D12GraphicsCommandList*L;static ID3D12Device*D;static struct mheap*vis;
static void rt_heaps(void){ID3D12DescriptorHeap*h[1]={&vis->iface};L->lpVtbl->SetDescriptorHeaps(L,1,h);want.nheaps=1;want.heaps[0]=h[0];}
static void rt_root(ID3D12RootSignature*r){L->lpVtbl->SetComputeRootSignature(L,r);if(want.root!=r){memset(want.tables,0,sizeof(want.tables));memset(want.c,0,sizeof(want.c));memset(want.va,0,sizeof(want.va));}want.root=r;}
static void rt_table(UINT i,UINT slot){L->lpVtbl->SetComputeRootDescriptorTable(L,i,G(vis,slot));want.tables[i]=G(vis,slot).ptr;}
static void rt_consts(UINT i,UINT n,const UINT*v){L->lpVtbl->SetComputeRoot32BitConstants(L,i,n,v,0);memcpy(want.c[i],v,n*4);}
/* fast_dispatch as fast_trial.h runs it with the check on: fq_before, the runtime's (F(2x2)) dispatch, fq_after */
static void rt_dispatch(ID3D12PipelineState*exact,uint64_t shader,UINT x,UINT y,UINT z){
 bindings[0].l=L;bindings[0].p=exact;nbinding=1;want.pso=exact;
 if(gpu.pso!=want.pso)m_setpso(L,want.pso);
 fq_before(L,shader,x,y,z);
 int ok=rt_state()&&gpu.pso==want.pso;
 char line[200];snprintf(line,sizeof(line),"INTEL shader=%016llx groups=%u,%u,%u STATE %s\n",(unsigned long long)shader,x,y,z,ok?"ok":"bad");logline(line);
 own_dispatches--;m_dispatch(L,x,y,z);   /* the runtime's own dispatch (logged as OWN for its pipeline, not counted) */
 fq_after(L,shader);
}
static void write_file(const char*name,const char*text){
 char path[1200];snprintf(path,sizeof(path),"%s\\%s",patchdir,name);FILE*f=fopen(path,"wb");if(!f){logline("TEST cannot write profile file\n");ExitProcess(3);}
 fwrite(text,1,strlen(text),f);fclose(f);
}
#define OTHER 0x1a3b0782583fef19ULL   /* F4Q2's 16 -> 16 encoder; its F(2x2) file is named exact-other */
#define NEVER 0x0123456789abcdefULL   /* a shader no form replaces */
static const uint64_t XU1_LAYERS[4]={0x1f27b449fb99a587ULL,0xf2e2e13fea432d20ULL,0x5654aa3800432b13ULL,0x4bb52a635e6d221aULL};
static ID3D12PipelineState*create(uint64_t h,const char*intel){
 D3D12_COMPUTE_PIPELINE_STATE_DESC cd={.CS={intel,strlen(intel)}};ID3D12PipelineState*p=NULL;
 HRESULT hr=f4q_compute(D,&cd,h,&IID_ID3D12PipelineState,(void**)&p);
 char line[200];snprintf(line,sizeof(line),"PSO %016llx hr=0x%08lx name=%s\n",(unsigned long long)h,(unsigned long)hr,p?((struct mobj*)p)->name:"none");logline(line);
 return p;
}
static void geometry(uint64_t h,ID3D12PipelineState*p,int row_x,int row_y,UINT row_z){
 bindings[0].l=L;bindings[0].p=p;nbinding=1;int x=row_x,y=row_y;UINT z=row_z;f4q_geometry(L,h,&x,&y,&z);
 char line[200];snprintf(line,sizeof(line),"GEOM %016llx pso=%s %d %d %u\n",(unsigned long long)h,p?((struct mobj*)p)->name:"none",x,y,z);logline(line);
}
/* the model owner's segment of one raw model against an independent product (Gp g Gp^T as two matrix products) */
static void pack_check(UINT bytes,unsigned seed){
 int8_t*raw=malloc(bytes);for(UINT i=0;i<bytes;i++){seed=seed*1103515245u+12345u;raw[i]=(int8_t)(seed>>16);}
 raw[0]=-128;raw[1]=127;   /* the extremes of int8 */
 UINT size=model_f4q_size(bytes);float*seg=calloc(1,size?size:16);
 model_f4q_pack(raw,bytes,seg,bytes==2304?F4Q_TBASE_2304:bytes==4608?F4Q_TBASE_4608:
               bytes==18432?F4Q2_TBASE_18432:bytes==73728?F4Q2_TBASE_73728:
               0);
 static const int GP[6][3]={{6,0,0},{-4,-4,-4},{-4,4,-4},{1,2,4},{1,-2,4},{0,0,24}};
 UINT chunks=bytes/2304,bad=0,count=0;long long maxabs=0;
 for(UINT s=0;s<chunks;s++)for(UINT k=0;k<16;k++)for(UINT c=0;c<16;c++){
  long long t[6][3];
  for(UINT i=0;i<6;i++)for(UINT b=0;b<3;b++){t[i][b]=0;for(UINT a=0;a<3;a++)t[i][b]+=(long long)GP[i][a]*raw[s*2304+(a*3+b)*256+(c>>2)*64+k*4+(c&3)];}
  for(UINT i=0;i<6;i++)for(UINT j=0;j<6;j++){
   long long u=0;for(UINT b=0;b<3;b++)u+=t[i][b]*GP[j][b];
   if((u<0?-u:u)>maxabs)maxabs=u<0?-u:u;
   if(seg[((s*6+i)*384u+(c*6+j)*4u+(k>>2))*4u+(k&3)]!=(float)u)bad++;
   count++;
  }
 }
 char line[200];snprintf(line,sizeof(line),"PACK bytes=%u segment=%u values=%u differing=%u maxabs=%lld\n",bytes,size,count,bad,maxabs);logline(line);
 free(seg);free(raw);
}

void mainCRTStartup(void){
 out=GetStdHandle(STD_OUTPUT_HANDLE);
 char*cmd=GetCommandLineA();
 int mode=strstr(cmd," shadow ")?4:strstr(cmd," layout ")?3:strstr(cmd," fallback ")?2:strstr(cmd," pack ")?5:strstr(cmd," switch ")?1:
          strstr(cmd," layout2 ")?6:strstr(cmd," fp16fallback ")?7:0;
 if(!mode){logline("TEST usage: test_f4q.exe switch|fallback|fp16fallback|layout|layout2|shadow|pack DIR\n");ExitProcess(2);}
 char*dir=strrchr(cmd,' ');snprintf(patchdir,sizeof(patchdir),"%s",dir?dir+1:".");
 if(mode==3)model_wino_enc16=1535&~64u;   /* no row16 segment: the F4Q segment would start elsewhere */
 if(mode==6)model_wino_enc16=1535&~(4u|16u);   /* no 18432- or 73728-byte layout: F4Q2's two larger layers stay off */
 HMODULE d3d12=LoadLibraryA("d3d12.dll");
 serialize=d3d12?(void*)GetProcAddress(d3d12,"D3D12SerializeVersionedRootSignature"):NULL;
 if(!serialize){logline("TEST no d3d12 serializer\n");ExitProcess(2);}
 mres_vtbl.GetDesc=mres_desc;mres_vtbl.GetGPUVirtualAddress=mres_va;mres_vtbl.Map=mres_map;mres_vtbl.Unmap=mres_unmap;
 mres_vtbl.AddRef=(void*)m_addref;mres_vtbl.Release=(void*)m_release;
 mheap_vtbl.GetCPUDescriptorHandleForHeapStart=mheap_cpu;mheap_vtbl.GetGPUDescriptorHandleForHeapStart=mheap_gpu;mheap_vtbl.Release=(void*)m_release;mheap_vtbl.AddRef=(void*)m_addref;
 mroot_vtbl.Release=(void*)m_release;mroot_vtbl.AddRef=(void*)m_addref;mpso_vtbl.Release=(void*)m_release;mpso_vtbl.AddRef=(void*)m_addref;
 dv.CreateRootSignature=d_root;dv.CreateUnorderedAccessView=d_uav;dv.CreateShaderResourceView=d_srv;dv.CreateConstantBufferView=d_cbv;
 dv.CopyDescriptorsSimple=d_copy_simple;dv.CopyDescriptors=d_copy;dv.CreateDescriptorHeap=d_heap;dv.GetDescriptorHandleIncrementSize=d_inc;dv.CreateCommittedResource=d_committed;
 lv.SetComputeRootSignature=l_root;lv.SetComputeRootDescriptorTable=l_table;lv.SetComputeRoot32BitConstant=l_constant;lv.SetComputeRoot32BitConstants=l_constants;
 lv.SetComputeRootConstantBufferView=l_va;lv.SetComputeRootShaderResourceView=l_va;lv.SetComputeRootUnorderedAccessView=l_va;lv.SetDescriptorHeaps=l_heaps;lv.Reset=l_reset;
 lv.ResourceBarrier=l_barrier;lv.CopyBufferRegion=l_copy;
 compute_original=m_compute;set_original=m_setpso;dispatch_original=m_dispatch;
 ID3D12DeviceVtbl before_d=dv;ID3D12GraphicsCommandListVtbl before_l=lv;
 static ID3D12Device dev;static ID3D12GraphicsCommandList list;dev.lpVtbl=&dv;list.lpVtbl=&lv;D=&dev;L=&list;
 /* the profile: the F(2x2) and F(4x4) files of the two targets and one other shader (each file holds its name) */
 write_file("b3941ac8ff95efe7.dxil","exact-dec");write_file("f030948d38e74671.dxil","exact-enc");write_file("1a3b0782583fef19.dxil","exact-other");
 write_file("b3941ac8ff95efe7.f4q.dxil","f4q-dec");if(mode!=2)write_file("f030948d38e74671.f4q.dxil","f4q-enc");
 write_file("1a3b0782583fef19.f4q.dxil","f4q-1a3b");write_file("e83e868f8d5d2c0f.dxil","exact-e83e");
 write_file("e83e868f8d5d2c0f.f4q.dxil","f4q-e83e");write_file("9e0080eee00255f2.dxil","exact-9e00");
 write_file("9e0080eee00255f2.f4q.dxil","f4q-9e00");write_file("0123456789abcdef.dxil","exact-0123");
 write_file("60edebbbd2f9fb69.dxil","exact-60ed");write_file("60edebbbd2f9fb69.f4q.dxil","f4q-60ed");
 write_file("b3ddf030f661d487.dxil","exact-b3dd");write_file("b3ddf030f661d487.f4q.dxil","f4q-b3dd");
 for(UINT i=0;i<4;i++){char name[40],text[16];snprintf(name,sizeof(name),"%016llx.dxil",(unsigned long long)XU1_LAYERS[i]);
  snprintf(text,sizeof(text),"exact-%04x",(unsigned)(XU1_LAYERS[i]>>48));write_file(name,text);}
 /* the FP16 forms the package ships, bits 1 and 2 (fp16fallback: e83e868f's, 1a3b0782's and 1f27b449's missing); none
  * for b3941ac8, f030948d and the row layers (bits 4 and 8), as in the package */
 if(mode!=7)write_file("1a3b0782583fef19.fp16.dxil","fp16-1a3b");
 if(mode!=7)write_file("e83e868f8d5d2c0f.fp16.dxil","fp16-e83e");
 write_file("9e0080eee00255f2.fp16.dxil","fp16-9e00");
 for(UINT i=0;i<4;i++){if(mode==7&&!i)continue;char name[40],text[16];snprintf(name,sizeof(name),"%016llx.fp16.dxil",(unsigned long long)XU1_LAYERS[i]);
  snprintf(text,sizeof(text),"fp16-%04x",(unsigned)(XU1_LAYERS[i]>>48));write_file(name,text);}
 const char*fp[5]={"f4q-check-uav-uint.dxil","f4q-check-uav-float.dxil","f4q-check-uav-sint.dxil","f4q-check-uav-raw.dxil","f4q-check-aux.dxil"};
 for(UINT i=0;i<5;i++)write_file(fp[i],fp[i]);
 if(mode==2)fail_bytecode="f4q-dec";
 if(mode==7)fail_bytecode="fp16-f2e2";
 /* fast_prepare: the settings (mfg_settings_init at load), then install_model_owner, f4q_configure, fq_install */
 mfg_settings_init();
 f4q_configure();
 char line[300];
 snprintf(line,sizeof(line),"CONFIG mode=%u\n",f4q_mode);logline(line);
 snprintf(line,sizeof(line),"SEGMENT 2304=%u 4608=%u 9216=%u\n",model_f4q_size(2304),model_f4q_size(4608),model_f4q_size(9216));logline(line);
 if(mode==5){pack_check(2304,1);pack_check(4608,2);
  if(f4q2_mask&2)pack_check(18432,3);
  if(f4q2_mask&4)pack_check(73728,4);
  logline("DONE\n");ExitProcess(0);}
 snprintf(line,sizeof(line),"SEGMENT2 18432=%u 73728=%u 36864=%u mask=%u\n",model_f4q_size(18432),model_f4q_size(73728),model_f4q_size(36864),f4q2_mask);
 logline(line);
 snprintf(line,sizeof(line),"SEGMENT3 2304=%u 4608=%u 9216=%u 18432=%u 36864=%u 73728=%u fp16=%u f4q3=%u\n",model_fp16_size(2304),model_fp16_size(4608),
          model_fp16_size(9216),model_fp16_size(18432),model_fp16_size(36864),model_fp16_size(73728),fp16_mask,f4q3_mask);
 logline(line);
 fq_install(D,L);
 snprintf(line,sizeof(line),"VTABLE unchanged=%d\n",!memcmp(&before_d,&dv,sizeof(dv))&&!memcmp(&before_l,&lv,sizeof(lv)));logline(line);
 if(mode!=4){
  /* compute_hook: the runtime creates its pipelines (Intel's bytecode stands in as text); then their geometry from the
   * profile's dispatch-scale rows (b3941ac8 1 4 1, f030948d 1 2 2, 1a3b0782 2 4 1) */
  ID3D12PipelineState*dec=create(FQ_DEC,"intel-dec"),*enc=create(FQ_ENC,"intel-enc"),*other=create(OTHER,"intel-other");
  ID3D12PipelineState*dec2=create(FQ_DEC,"intel-dec");   /* a second pipeline of the same shader (another root signature) */
  geometry(FQ_DEC,dec,1,4,1);geometry(FQ_DEC,dec2,1,4,1);geometry(FQ_ENC,enc,1,2,2);geometry(OTHER,other,2,4,1);
  /* F4Q2's other two layers from their dispatch-scale rows (e83e868f 1 1 4, 9e0080ee 1 1 8), the row layers from their
   * identity rows (1 1 1), the four F(2x2) layers of FP16 bit 2 from theirs (1f27b449 1 2 4, f2e2e13f 1 1 2, 5654aa38
   * 2 1 2, 4bb52a63 1 1 4), and a shader that is never a target (1 1 2) */
  ID3D12PipelineState*e83e=create(F4Q2_E83E,"intel-e83e"),*e9e0=create(F4Q2_9E00,"intel-9e00"),*never=create(NEVER,"intel-0123");
  geometry(F4Q2_E83E,e83e,1,1,4);geometry(F4Q2_9E00,e9e0,1,1,8);geometry(NEVER,never,1,1,2);
  ID3D12PipelineState*r60=create(F4Q3_60ED,"intel-60ed"),*rb3=create(F4Q3_B3DD,"intel-b3dd");
  geometry(F4Q3_60ED,r60,1,1,1);geometry(F4Q3_B3DD,rb3,1,1,1);
  static const int XROW[4][3]={{1,2,4},{1,1,2},{2,1,2},{1,1,4}};
  for(UINT i=0;i<4;i++){ID3D12PipelineState*x=create(XU1_LAYERS[i],"intel-xu1");geometry(XU1_LAYERS[i],x,XROW[i][0],XROW[i][1],(UINT)XROW[i][2]);}
  ID3D12PipelineState*stranger=(ID3D12PipelineState*)mk(&mpso_vtbl,"stranger");geometry(FQ_DEC,stranger,1,4,1);
  fq_frame_tick();fq_finish();
  geometry(FQ_DEC,dec,1,4,1);   /* after the context's release: its F(4x4) pipeline table is gone */
  snprintf(line,sizeof(line),"TICKS %ld OWN %u\n",(long)fq_ticks,own_dispatches);logline(line);logline("DONE\n");ExitProcess(0);
 }
 /* the check: the runtime's heap, views, root signature and pipelines */
 D3D12_DESCRIPTOR_HEAP_DESC hd={.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,.NumDescriptors=256,.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE};
 D->lpVtbl->CreateDescriptorHeap(D,&hd,&IID_ID3D12DescriptorHeap,(void**)&vis);
 struct mres*model=buf("model",48400+36864);test_model=&model->iface;
 struct mres*model2=buf("model2",96784+73728);
 struct mres*low=tex("low",640,368,1,DXGI_FORMAT_R32G32B32A32_UINT,0),*skip=tex("skip",1280,736,1,DXGI_FORMAT_R32G32B32A32_UINT,0);
 struct mres*dst=tex("dec-out",1280,736,1,DXGI_FORMAT_R32G32B32A32_UINT,1),*dst_half=tex("dec-out-half",640,368,1,DXGI_FORMAT_R32G32B32A32_UINT,1);
 struct mres*src=tex("enc-in",640,368,1,DXGI_FORMAT_R32G32B32A32_UINT,0),*enc_out=tex("enc-out",320,184,2,DXGI_FORMAT_R32G32B32A32_UINT,1);
 D3D12_SHADER_RESOURCE_VIEW_DESC sv={.Format=DXGI_FORMAT_R32G32B32A32_UINT,.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2DARRAY,.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING};
 sv.Texture2DArray.MipLevels=1;sv.Texture2DArray.ArraySize=1;
 D->lpVtbl->CreateShaderResourceView(D,&low->iface,&sv,C(vis,0));D->lpVtbl->CreateShaderResourceView(D,&skip->iface,&sv,C(vis,4));
 D->lpVtbl->CreateShaderResourceView(D,&src->iface,&sv,C(vis,10));
 D3D12_SHADER_RESOURCE_VIEW_DESC mv={.Format=DXGI_FORMAT_UNKNOWN,.ViewDimension=D3D12_SRV_DIMENSION_BUFFER,.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING};
 mv.Buffer.NumElements=5329;mv.Buffer.StructureByteStride=16;D->lpVtbl->CreateShaderResourceView(D,&model->iface,&mv,C(vis,1));
 mv.Buffer.NumElements=10657;D->lpVtbl->CreateShaderResourceView(D,&model2->iface,&mv,C(vis,11));
 D3D12_UNORDERED_ACCESS_VIEW_DESC uv={.Format=DXGI_FORMAT_R32G32B32A32_UINT,.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2DARRAY};uv.Texture2DArray.ArraySize=1;
 D->lpVtbl->CreateUnorderedAccessView(D,&dst->iface,NULL,&uv,C(vis,5));
 D->lpVtbl->CopyDescriptorsSimple(D,5,C(vis,20),C(vis,0),D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);   /* the half-size table: a copy, then its own output */
 D->lpVtbl->CreateUnorderedAccessView(D,&dst_half->iface,NULL,&uv,C(vis,25));
 uv.Texture2DArray.ArraySize=2;D->lpVtbl->CreateUnorderedAccessView(D,&enc_out->iface,NULL,&uv,C(vis,14));
 /* the row layers' own outputs (one 16-channel slice each), tables at 30 and 40 of the encoder root (UAV at +4) */
 struct mres*row60=tex("row60-out",640,360,1,DXGI_FORMAT_R32G32B32A32_UINT,1),*rowb3=tex("rowb3-out",320,180,1,DXGI_FORMAT_R32G32B32A32_UINT,1);
 uv.Texture2DArray.ArraySize=1;D->lpVtbl->CreateUnorderedAccessView(D,&row60->iface,NULL,&uv,C(vis,34));
 D->lpVtbl->CreateUnorderedAccessView(D,&rowb3->iface,NULL,&uv,C(vis,44));
 /* decoder root: table (SRV t0..t4 at 0..4, UAV u0 at 5) + Dims (2 constants); encoder root: table (SRV t0..t3, UAV u0) */
 D3D12_DESCRIPTOR_RANGE1 rd[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,5,0,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,0,0,0,D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND}};
 D3D12_ROOT_PARAMETER1 pd[2]={0};pd[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;pd[0].DescriptorTable.NumDescriptorRanges=2;pd[0].DescriptorTable.pDescriptorRanges=rd;
 pd[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;pd[1].Constants.Num32BitValues=2;
 D3D12_ROOT_SIGNATURE_DESC1 sd={2,pd,0,NULL,0};ID3D12RootSignature*root_dec=make_root(D,&sd);
 D3D12_DESCRIPTOR_RANGE1 re[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,0,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,0,0,0,D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND}};
 D3D12_ROOT_PARAMETER1 pe_[1]={0};pe_[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;pe_[0].DescriptorTable.NumDescriptorRanges=2;pe_[0].DescriptorTable.pDescriptorRanges=re;
 D3D12_ROOT_SIGNATURE_DESC1 se={1,pe_,0,NULL,0};ID3D12RootSignature*root_enc=make_root(D,&se);
 /* compute_hook: the runtime creates its pipelines; the add-on's F(2x2) replacement, then the check's F(4x4) pipeline */
 D3D12_COMPUTE_PIPELINE_STATE_DESC cd={.pRootSignature=root_dec,.CS={"intel-dec",9}};
 ID3D12PipelineState*exact_dec=NULL,*exact_enc=NULL,*other=NULL;
 f4q_compute(D,&cd,FQ_DEC,&IID_ID3D12PipelineState,(void**)&exact_dec);
 cd.pRootSignature=root_enc;cd.CS.pShaderBytecode="intel-enc";f4q_compute(D,&cd,FQ_ENC,&IID_ID3D12PipelineState,(void**)&exact_enc);
 cd.CS.pShaderBytecode="intel-other";f4q_compute(D,&cd,OTHER,&IID_ID3D12PipelineState,(void**)&other);
 snprintf(line,sizeof(line),"PIPELINES dec=%s enc=%s other=%s\n",((struct mobj*)exact_dec)->name,((struct mobj*)exact_enc)->name,((struct mobj*)other)->name);logline(line);
 ID3D12PipelineState*e83e_exact=NULL,*e9e0_exact=NULL;
 cd.CS.pShaderBytecode="intel-e83e";f4q_compute(D,&cd,F4Q2_E83E,&IID_ID3D12PipelineState,(void**)&e83e_exact);
 cd.CS.pShaderBytecode="intel-9e00";f4q_compute(D,&cd,F4Q2_9E00,&IID_ID3D12PipelineState,(void**)&e9e0_exact);
 snprintf(line,sizeof(line),"PIPELINES2 e83e=%s 9e00=%s\n",((struct mobj*)e83e_exact)->name,((struct mobj*)e9e0_exact)->name);logline(line);
 ID3D12PipelineState*r60_exact=NULL,*rb3_exact=NULL;
 cd.CS.pShaderBytecode="intel-60ed";f4q_compute(D,&cd,F4Q3_60ED,&IID_ID3D12PipelineState,(void**)&r60_exact);
 cd.CS.pShaderBytecode="intel-b3dd";f4q_compute(D,&cd,F4Q3_B3DD,&IID_ID3D12PipelineState,(void**)&rb3_exact);
 snprintf(line,sizeof(line),"PIPELINES3 60ed=%s b3dd=%s\n",((struct mobj*)r60_exact)->name,((struct mobj*)rb3_exact)->name);logline(line);
 geometry(FQ_DEC,exact_dec,1,4,1);
 /* three real frames: per generated frame the decoder at both sizes and the encoder, and one other dispatch */
 for(UINT frame=0;frame<3;frame++){
  fq_frame_tick();
  rt_heaps();
  rt_root(root_enc);rt_table(0,10);rt_dispatch(exact_enc,FQ_ENC,80,12,1);
  rt_dispatch(other,OTHER,40,23,1);
  rt_root(root_dec);rt_table(0,20);UINT dh[2]={640,368};rt_consts(1,2,dh);rt_dispatch(exact_dec,FQ_DEC,40,12,1);
  rt_table(0,0);UINT df[2]={1280,736};rt_consts(1,2,df);rt_dispatch(exact_dec,FQ_DEC,80,23,1);
  /* F4Q2's other two layers (1a3b0782 is "other" above; the encoder root and views stand in for theirs; Intel's 1440p
   * dispatches: 40 x 12, 10 x 12) */
  if(f4q2_mask){rt_root(root_enc);rt_table(0,10);rt_dispatch(e83e_exact,F4Q2_E83E,40,12,1);rt_dispatch(e9e0_exact,F4Q2_9E00,10,12,1);}
  /* the row layers at Intel's 1440p dispatches (80 x 45, 40 x 23), each with its own output view */
  if(f4q3_mask){rt_root(root_enc);rt_table(0,30);rt_dispatch(r60_exact,F4Q3_60ED,80,45,1);rt_table(0,40);rt_dispatch(rb3_exact,F4Q3_B3DD,40,23,1);}
 }
 /* geometry refusal: a target dispatched with z != 1 */
 rt_dispatch(exact_dec,FQ_DEC,80,23,2);
 /* a fake readback: the GPU's counters as the CPU would read them (head and tail stamps agree in slot 1 only) */
 UINT*rb=(UINT*)fq_rb;
 rb[0]=5;rb[FQ_WORDS-1]=6;
 UINT*s1=rb+FQ_WORDS;s1[0]=7;s1[FQ_WORDS-1]=7;s1[1]=0;s1[2]=9;
 s1[FQ_PTBASE+(0*8+4)*2]=3;s1[FQ_PTBASE+(1*8+4)*2]=2;s1[FQ_PTBASE+(1*8+4)*2+1]=1;s1[FQ_PTBASE+(2*8+4)*2]=3;
 if(f4q2_mask){s1[FQ_PTBASE+(3*8+4)*2]=3;s1[FQ_PTBASE+(4*8+4)*2]=3;s1[FQ_PTBASE+(5*8+4)*2]=2;s1[FQ_PTBASE+(5*8+4)*2+1]=1;}
 if(f4q3_mask){s1[FQ_PTBASE+(6*8+4)*2]=3;s1[FQ_PTBASE+(7*8+4)*2]=2;s1[FQ_PTBASE+(7*8+4)*2+1]=1;}
 fq_status("test");
 for(UINT i=0;i<res_count;i++){snprintf(line,sizeof(line),"REFS before-finish %s %ld\n",res_all[i]->name,(long)res_all[i]->refs);logline(line);}
 fq_finish();
 for(UINT i=0;i<res_count;i++){snprintf(line,sizeof(line),"REFS after-finish %s %ld\n",res_all[i]->name,(long)res_all[i]->refs);logline(line);}
 for(UINT i=0;i<pso_count;i++){snprintf(line,sizeof(line),"REFS pso %s %ld\n",psos_all[i]->name,(long)psos_all[i]->refs);logline(line);}
 snprintf(line,sizeof(line),"TOTALS own=%u barriers=%u copies=%u ticks_after_finish=%ld\n",own_dispatches,barriers,copies,(long)fq_ticks);logline(line);
 logline("DONE\n");
 ExitProcess(0);
}
