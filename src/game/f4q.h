/* SPDX-License-Identifier: MIT
 * F4Q (XEFG_F4Q, the multi-frame proxy since FreeFG 1.1): which pipelines run this project's F(4x4) kernels for the
 * U-Net decoder b3941ac8 and encoder f030948d, since 1.1.2 (F4Q2) for the encoders 1a3b0782, e83e868f and 9e0080ee and
 * (F4Q3) for the row layers 60edebbb and b3ddf030, which pipelines run the FP16 forms (1.1.2), their dispatch geometry,
 * and the in-game check (switches, model segments and the tier: src/model_f4q.h).
 *
 *   F4Q on (default)       compute_hook creates b3941ac8 and f030948d (with F4Q2 on, its default, also 1a3b0782,
 *                          e83e868f and 9e0080ee; with F4Q3, also 60edebbb and b3ddf030) from <hash>.f4q.dxil instead of
 *                          the F(2x2) <hash>.dxil (F4Q_REPLACE lines); dispatches bound to such a pipeline take the F(4x4)
 *                          groups: b3941ac8 32 x 16 px per group (x / 2, y x 2 of Intel's dispatch), f030948d 16 x 8 pooled
 *                          px (x / 4, y x 2, two output slices in z); the F4Q2 layers 16 x 8 pooled px of one output slice
 *                          per group: 1a3b0782 x 1, y x 2, one slice; e83e868f x / 4, y x 1, four slices; 9e0080ee x / 2,
 *                          y / 2, eight slices; the F4Q3 row layers 32 x 16 px of their one output slice: x / 4, y / 2 (the
 *                          dispatch-scale.txt rows of the F(2x2) and 1D kernels describe Intel's dispatch; the row layers'
 *                          rows are identities). When a F(4x4) pipeline cannot be created, that pipeline is created from
 *                          the F(2x2) file instead and keeps the F(2x2) geometry (one F4Q_FALLBACK line): the geometry
 *                          follows the pipeline a dispatch binds.
 *   FP16 forms (default)   while their bits are on (src/model_f4q.h fp16_mask; this build turns on bits 1 and 2), a
 *                          target's F(4x4) pipeline is created from <hash>.fp16.dxil (bit 1: the F4Q2 layers that are on;
 *                          bit 4: b3941ac8, f030948d; same geometry), and 1f27b449, f2e2e13f, 5654aa38, 4bb52a63 (bit 2) and
 *                          60edebbb, b3ddf030 (bit 8, F4Q3 then off) are created from <hash>.fp16.dxil instead of their
 *                          F(2x2) / 1D <hash>.dxil (same geometry): FP16_REPLACE lines. A missing FP16 file (FP16_FALLBACK)
 *                          of e83e868f or 9e0080ee, whose FP32 table the owner wrote as FP16 in place, makes that pipeline
 *                          F(2x2) (F4Q_FALLBACK too); of 1a3b0782, b3941ac8 or f030948d (FP16 copies) the F(4x4) file
 *                          runs; of a bit 2 or 8 layer, its F(2x2) / 1D file. A failed creation: FP16_REPLACE, then
 *                          F4Q_FALLBACK (target) or FP16_FALLBACK (bit 2 or 8).
 *   BC250_XEFG_F4Q_SHADOW=1 (diagnostic, off by default; logs nothing unless set)
 *                          the F(2x2) kernels keep the output; at each of their dispatches the F(4x4) kernel runs first,
 *                          into the same output view, which is fingerprinted, then the runtime's dispatch runs the F(2x2)
 *                          kernel, its output is fingerprinted, and an own GPU pass compares the two fingerprints and
 *                          adds to equal / differ counters. The CPU reads only the counters (F4Q_COUNT lines, every 100
 *                          real frames and at release). Both kernels and the check passes are this project's own code
 *                          (src/kernels/f4q_check.hlsl); nothing of the content leaves the GPU. The FP16 forms are off.
 * Points of the check: 0 = b3941ac8 at full size (output width >= 1024), 1 = b3941ac8 at half size, 2 = f030948d; with F4Q2
 * on, 3 = 1a3b0782, 4 = e83e868f, 5 = 9e0080ee; with F4Q3, 6 = 60edebbb, 7 = b3ddf030.
 *
 * Check mechanics: root signature layouts, UAV provenance through Create/Copy calls, shader-visible heaps and every
 * compute root argument per command list are tracked (only while the check runs); an own pass binds its own heap and
 * root signature, dispatches, and restores the runtime's heaps, root signature, every root argument and pipeline. Views
 * are cached with a reference on the resource (released at context release).
 * Fast-log lines: F4Q_CONFIG, F4Q2_CONFIG, FP16_CONFIG, F4Q3_CONFIG, F4Q_SEGMENT and FP16_SEGMENT (src/model_f4q.h),
 * F4Q_REPLACE, F4Q_FALLBACK, FP16_REPLACE, FP16_FALLBACK; with the check only: F4Q_SHADOW_PSO, F4Q_INSTALLED (and
 * F4Q2_INSTALLED, F4Q3_INSTALLED), F4Q_STATUS (and F4Q2_STATUS, F4Q3_STATUS) + F4Q_COUNT, F4Q_SUMMARY, F4Q_SKIP, F4Q_STOP.
 */
#ifndef FQ_MODEL_COUNT
#define FQ_MODEL_COUNT() (model_count)
#define FQ_MODEL_R(i) (models[i].r)
#endif
#define FQ_DEC 0xb3941ac8ff95efe7ULL
#define FQ_ENC 0xf030948d38e74671ULL
#define FQ_LISTS 128
#define FQ_PARAMS 16
#define FQ_ROOTS 512
#define FQ_RANGES 8
#define FQ_VIEWS 65536
#define FQ_HEAPS 64
#define FQ_SET 8
#define FQ_SLOTS 4096
#define FQ_DESC 1024
#define FQ_DESC_BASE 4
#define FQ_WORDS 8464
#define FQ_PTBASE 16
#define FQ_RB 4
#define FQ_PSOS 5
#define FQ_PAIRS 32
#define FQ_POINTS 8        /* 0..2 F4Q, 3..5 the F4Q2 encoders, 6..7 the F4Q3 row layers */
#define FQ_LOG_EVERY 100   /* real frames between F4Q_STATUS lines of the check */
#define F4Q_PIPELINES 64
enum { FQV_NONE = 0, FQV_SRV = 1, FQV_UAV = 2 };
enum { FQK_OBJECTS, FQK_LIST, FQK_ROOT, FQK_PSO, FQK_PAIR, FQK_DESC_FULL, FQK_TARGETS, FQK_GEOMETRY, FQK_UNSUPPORTED, FQK_COUNT };
static const char*const fq_skip_names[FQK_COUNT]={"objects","list","root","pso","pair","desc_full","targets","geometry","unsupported"};
static const char*const fq_point_names[FQ_POINTS]={"b3941ac8-full","b3941ac8-half","f030948d","1a3b0782","e83e868f","9e0080ee",
                                                   "60edebbb","b3ddf030"};
/* the check's fingerprint and compare kernels (src/kernels/f4q_check.hlsl, KIND 0..3 on a UAV view, KIND 4 = aux) */
static const char*const fq_pso_names[FQ_PSOS]={"f4q-check-uav-uint.dxil","f4q-check-uav-float.dxil","f4q-check-uav-sint.dxil","f4q-check-uav-raw.dxil","f4q-check-aux.dxil"};

struct fq_view { SIZE_T cpu; UINT kind, has_desc; ID3D12Resource *r; union { D3D12_SHADER_RESOURCE_VIEW_DESC srv; D3D12_UNORDERED_ACCESS_VIEW_DESC uav; } d; };
struct fq_root { ID3D12RootSignature *r; UINT nparams; struct { UINT table, nranges; struct { UINT type, count, offset; } ranges[FQ_RANGES]; } p[FQ_PARAMS]; };
struct fq_list {
 ID3D12GraphicsCommandList *l; ID3D12RootSignature *root; ID3D12DescriptorHeap *heaps[2]; UINT nheaps, broken;
 struct { UINT kind; UINT64 v; UINT c[64]; UINT64 cmask; } p[FQ_PARAMS];   /* kind 1 table, 2 constants, 3 cbv, 4 srv, 5 uav */
};
struct fq_target { ID3D12Resource *r; UINT kind, desc, w, h, s, mip, first, fmt; UINT64 words, off, bytes_begin; };
struct fq_batch { UINT base, n, tag; };

static struct {
 UINT on, stopped, cursor, tag, pending_point, pending_n, status_count;
 UINT64 dispatches[FQ_POINTS], compares, skips[FQK_COUNT];
 LONG last_log_tick;
 struct fq_target t[FQ_SET]; struct fq_batch b;   /* the F(4x4) fingerprint of the pending dispatch */
} fq;
static volatile LONG fq_ticks;
static SRWLOCK fq_lock = SRWLOCK_INIT;
static struct { ID3D12PipelineState *exact, *f4q; uint64_t hash; } fq_pairs[FQ_PAIRS]; static UINT fq_pair_count;
static struct fq_root fq_roots[FQ_ROOTS]; static UINT fq_root_count;
static struct fq_view fq_views[FQ_VIEWS];
static struct { ID3D12DescriptorHeap *h; SIZE_T cpu; UINT64 gpu; UINT count; } fq_heaps[FQ_HEAPS]; static UINT fq_heap_count;
static struct fq_list fq_lists[FQ_LISTS]; static UINT fq_list_count;
static struct { uint64_t key; ID3D12Resource *r; } fq_descs[FQ_DESC]; static UINT fq_ndesc;
static ID3D12Device *fq_device; static UINT fq_stride;
static ID3D12RootSignature *fq_root_sig; static ID3D12PipelineState *fq_pso[FQ_PSOS]; static ID3D12DescriptorHeap *fq_heap;
static ID3D12Resource *fq_slots, *fq_counters, *fq_readback; static const volatile UINT *fq_rb; static UINT fq_objects_tried, fq_rb_next;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateRootSignature) fq_next_create_root;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateUnorderedAccessView) fq_next_uav;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateShaderResourceView) fq_next_srv;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateConstantBufferView) fq_next_cbv;
static __typeof__(((ID3D12DeviceVtbl*)0)->CopyDescriptorsSimple) fq_next_copy_simple;
static __typeof__(((ID3D12DeviceVtbl*)0)->CopyDescriptors) fq_next_copy;
static __typeof__(((ID3D12DeviceVtbl*)0)->CreateDescriptorHeap) fq_next_heap;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRootSignature) fq_next_set_root;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRootDescriptorTable) fq_next_table;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRoot32BitConstant) fq_next_constant;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRoot32BitConstants) fq_next_constants;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRootConstantBufferView) fq_next_root_cbv;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRootShaderResourceView) fq_next_root_srv;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetComputeRootUnorderedAccessView) fq_next_root_uav;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->SetDescriptorHeaps) fq_next_heaps;
static __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->Reset) fq_next_reset;
#define FQ_INNER(model, next) ((model) ? (model) : (next))
static uint64_t fq_fnv(uint64_t h, const void *p, size_t n){const unsigned char*b=p;for(size_t i=0;i<n;i++)h=(h^b[i])*0x100000001b3ULL;return h;}
#define FQ_FNV0 0xcbf29ce484222325ULL
/* F4Q's two pipelines, and F4Q2's and F4Q3's layers while they are on (f4q2_bit, f4q3_bit: 0 for every shader while off) */
static int fq_target_shader(uint64_t s){return s==FQ_DEC||s==FQ_ENC||f4q2_bit(s)||f4q3_bit(s);}
/* the F(4x4) groups of an F4Q2 layer from Intel's dispatch of it (Intel's group covers 16 x 16 pooled px of 1a3b0782,
 * 4 x 8 of e83e868f, 8 x 4 of 9e0080ee: release/profile/dispatch-scale.txt with the F(2x2) group sizes); the F(4x4)
 * group covers 16 x 8 pooled px of one 16-channel output slice (z); a negative factor divides, rounding up */
static int f4q2_geometry(uint64_t s,int*sx,int*sy,UINT*sz){
 if(s==F4Q2_1A3B){*sx=1;*sy=2;*sz=1;return 1;}
 if(s==F4Q2_E83E){*sx=-4;*sy=1;*sz=4;return 1;}
 if(s==F4Q2_9E00){*sx=-2;*sy=-2;*sz=8;return 1;}
 /* F4Q3: Intel's group covers 8 x 8 output px of a row layer (the 1D kernel's 4 x 8 threads, two px each, at its identity
  * dispatch-scale row); the unpooled F(4x4) group covers 32 x 16 px of the one 16-channel output slice */
 if(s==F4Q3_60ED||s==F4Q3_B3DD){*sx=-4;*sy=-2;*sz=1;return 1;}
 return 0;
}
static void fq_skip(UINT why,uint64_t shader){
 fq.skips[why]++;
 if(fq.skips[why]<=4){char line[200];snprintf(line,sizeof(line),"F4Q_SKIP %s shader=%016llx count=%llu\n",fq_skip_names[why],(unsigned long long)shader,(unsigned long long)fq.skips[why]);logline(line);}
}

/* ---- the F(4x4) pipelines and their geometry (compute_hook and dispatch_hook, both under fast_record_lock) */
static struct { ID3D12PipelineState *p; uint64_t hash; } f4q_pipelines[F4Q_PIPELINES]; static UINT f4q_pipeline_count;
/* compute_hook: create this target from its F(4x4) file (F4Q on, room in the table to follow its geometry) */
static int f4q_replaces(uint64_t h){return f4q_mode==F4Q_ON&&fq_target_shader(h)&&f4q_pipeline_count<F4Q_PIPELINES;}
/* <hash><suffix>.dxil: its bytes (the caller frees them) and size, or NULL when it cannot be opened */
static void*f4q_file(uint64_t h,const char*suffix,DWORD*size){
 char path[1200];snprintf(path,sizeof(path),"%s\\%016llx%s.dxil",patchdir,(unsigned long long)h,suffix);
 HANDLE f=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);if(f==INVALID_HANDLE_VALUE)return NULL;
 DWORD n;*size=GetFileSize(f,NULL);void*bytes=malloc(*size);if(!bytes||!ReadFile(f,bytes,*size,&n,NULL)||n!=*size)ExitProcess(12);
 CloseHandle(f);return bytes;
}
/* FP16 forms: the F(4x4) targets that read an FP16 table (bit 1: F4Q2's layers that are on; bit 4: b3941ac8, f030948d) */
static int fp16_f4q_target(uint64_t h){return ((fp16_mask&FP16_F4Q2)&&f4q2_bit(h))||((fp16_mask&FP16_F4Q)&&(h==FQ_DEC||h==FQ_ENC));}
/* and the F(2x2) / 1D layers that run packed-FP16 MACs (bit 2: four XU-1 layers; bit 8: the row layers) */
static int fp16_pk_layer(uint64_t h){
 if(fp16_mask&FP16_XU1)if(h==0x1f27b449fb99a587ULL||h==0xf2e2e13fea432d20ULL||h==0x5654aa3800432b13ULL||h==0x4bb52a635e6d221aULL)return 1;
 return (fp16_mask&FP16_ROW)&&(h==F4Q3_60ED||h==F4Q3_B3DD);
}
static LONG fp16_lines;
static void fp16_line(const char*what,uint64_t h,DWORD size,const char*tail){
 if(InterlockedIncrement(&fp16_lines)>64)return;
 char line[300],bytes[24]="";if(size)snprintf(bytes,sizeof(bytes)," %lu",(unsigned long)size);
 snprintf(line,sizeof(line),"%s %016llx %016llx.fp16.dxil%s%s\n",what,(unsigned long long)h,(unsigned long long)h,bytes,tail);
 logline(line);
}
/* <hash>.dxil, or a target's F(4x4) file when f4q: <hash>.fp16.dxil while its FP16 form is on, else <hash>.f4q.dxil.
 * *form names the file read (".f4q" or ".fp16"). A missing FP16 file of e83e868f / 9e0080ee (their table is FP16 in
 * place) gives NULL, so the F(2x2) kernel runs; of another target, its .f4q.dxil. */
static void*f4q_read(uint64_t h,int f4q,DWORD*size,const char**form){
 *form=f4q?".f4q":"";
 if(f4q&&fp16_f4q_target(h)){
  void*bytes=f4q_file(h,".fp16",size);
  if(bytes){*form=".fp16";fp16_line("FP16_REPLACE",h,*size,"");return bytes;}
  int inplace=h==F4Q2_E83E||h==F4Q2_9E00;
  fp16_line("FP16_FALLBACK",h,0,inplace?" cannot be read: the F(2x2) kernel runs (its table is FP16 in place)":" cannot be read: the F(4x4) file runs");
  if(inplace)return NULL;
 }
 return f4q_file(h,f4q?".f4q":"",size);
}
static void f4q_fallback(uint64_t h,const char*why,HRESULT hr){
 char line[240];snprintf(line,sizeof(line),"F4Q_FALLBACK %016llx %s (hr=0x%08lx): the F(2x2) kernel runs for this pipeline\n",
                         (unsigned long long)h,why,(unsigned long)hr);logline(line);
}
static void f4q_note_pipeline(ID3D12PipelineState*p,uint64_t h,DWORD size,const char*form){
 f4q_pipelines[f4q_pipeline_count].p=p;f4q_pipelines[f4q_pipeline_count++].hash=h;
 char line[200];snprintf(line,sizeof(line),"F4Q_REPLACE %016llx %016llx%s.dxil %lu\n",(unsigned long long)h,(unsigned long long)h,form,(unsigned long)size);logline(line);
}
/* dispatch_hook, for a shader with a dispatch-scale.txt row: the F(4x4) groups when the list binds a F(4x4) pipeline */
static void f4q_geometry(ID3D12GraphicsCommandList*l,uint64_t shader,int*sx,int*sy,UINT*sz){
 if(!f4q_pipeline_count||!fq_target_shader(shader))return;
 ID3D12PipelineState*bound=NULL;for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)bound=bindings[b].p;
 for(UINT i=0;i<f4q_pipeline_count;i++)if(f4q_pipelines[i].p==(void*)bound&&f4q_pipelines[i].hash==shader){
  if(f4q2_geometry(shader,sx,sy,sz))return;
  if(shader==FQ_DEC){*sx=-2;*sy=2;*sz=1;}else{*sx=-4;*sy=2;*sz=2;}
  return;
 }
}
/* the F(4x4) groups from Intel's own (unscaled) dispatch of a target, for the check's F(4x4) pass */
static int fq_groups(uint64_t shader,UINT x,UINT y,UINT z,UINT*gx,UINT*gy,UINT*gz){
 if(z!=1||!x||!y||y>32767)return 0;
 if(shader==FQ_DEC){*gx=(x+1)/2;*gy=y*2;*gz=1;return 1;}
 if(shader==FQ_ENC){*gx=(x+3)/4;*gy=y*2;*gz=2;return 1;}
 int sx,sy;UINT sz;
 if(f4q2_geometry(shader,&sx,&sy,&sz)){
  *gx=sx>0?x*(UINT)sx:(x+(UINT)(-sx)-1)/(UINT)(-sx);*gy=sy>0?y*(UINT)sy:(y+(UINT)(-sy)-1)/(UINT)(-sy);*gz=sz;return 1;
 }
 return 0;
}
/* compute_hook (check only): beside the F(2x2) pipeline of a target, its F(4x4) pipeline from the same description */
static void fq_capture(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,uint64_t h,ID3D12PipelineState*exact){
 if(f4q_mode!=F4Q_SHADOW||!fq_target_shader(h))return;
 DWORD length=0;const char*form;void*bytes=f4q_read(h,1,&length,&form);if(!bytes){fq_skip(FQK_PSO,h);return;}
 D3D12_COMPUTE_PIPELINE_STATE_DESC copy=*desc;copy.CS.pShaderBytecode=bytes;copy.CS.BytecodeLength=(SIZE_T)length;copy.CachedPSO=(D3D12_CACHED_PIPELINE_STATE){0};
 ID3D12PipelineState*p=NULL;HRESULT hr=compute_original(d,&copy,&IID_ID3D12PipelineState,(void**)&p);free(bytes);
 if(FAILED(hr)||!p){fq_skip(FQK_PSO,h);return;}
 AcquireSRWLockExclusive(&fq_lock);
 if(fq_pair_count<FQ_PAIRS){fq_pairs[fq_pair_count].exact=exact;fq_pairs[fq_pair_count].f4q=p;fq_pairs[fq_pair_count++].hash=h;}
 else{ID3D12PipelineState_Release(p);p=NULL;}
 ReleaseSRWLockExclusive(&fq_lock);
 char line[200];snprintf(line,sizeof(line),"F4Q_SHADOW_PSO %016llx bytes=%lu %s\n",(unsigned long long)h,(unsigned long)length,p?"ok":"table full");logline(line);
}
/* compute_hook (src/probe.c) in this build: a shader the profile manifest lists is created from its replacement file
 * (REPLACE line); a F4Q target from its F(4x4) file while F4Q is on (f4q_read: <hash>.fp16.dxil or <hash>.f4q.dxil), and
 * from the F(2x2) <hash>.dxil when that file cannot be read or its pipeline cannot be created (F4Q_FALLBACK); a layer of
 * FP16 bit 2 or 8 from <hash>.fp16.dxil, its F(2x2) / 1D <hash>.dxil when that cannot be read or fails (FP16_FALLBACK);
 * other shaders as Intel built them. With the check on, a target's F(4x4) pipeline is created beside its F(2x2) one
 * (fq_capture). */
static HRESULT f4q_compute(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,uint64_t h,REFIID iid,void**out){
 D3D12_COMPUTE_PIPELINE_STATE_DESC copy=*desc;void*replacement=NULL;DWORD loaded=0;int f4q=0,pk=0;char line[160];const char*form="";
 if(*patchdir&&profile_lists_replacement(h)){
  f4q=f4q_replaces(h);
  if(f4q&&!(replacement=f4q_read(h,1,&loaded,&form))){f4q_fallback(h,"its F4Q file cannot be read",S_OK);f4q=0;}
  if(!replacement&&fp16_pk_layer(h)){
   if((replacement=f4q_file(h,".fp16",&loaded)))pk=1;
   else fp16_line("FP16_FALLBACK",h,0," cannot be read: the F(2x2) / 1D kernel runs");
  }
  if(!replacement)replacement=f4q_file(h,"",&loaded);
  if(replacement){
   copy.CS.pShaderBytecode=replacement;copy.CS.BytecodeLength=loaded;copy.CachedPSO=(D3D12_CACHED_PIPELINE_STATE){0};
   snprintf(line,sizeof(line),"REPLACE %016llx %lu\n",(unsigned long long)h,(unsigned long)loaded);logline(line);
  }
 }
 HRESULT hr=compute_original(d,&copy,iid,out);
 if((f4q||pk)&&FAILED(hr)){
  if(f4q)f4q_fallback(h,"pipeline creation failed",hr);
  else{snprintf(line,sizeof(line)," pipeline creation failed (hr=0x%08lx): the F(2x2) / 1D kernel runs",(unsigned long)hr);fp16_line("FP16_FALLBACK",h,loaded,line);}
  f4q=pk=0;free(replacement);
  if((replacement=f4q_file(h,"",&loaded))){copy.CS.pShaderBytecode=replacement;copy.CS.BytecodeLength=loaded;}else copy.CS=desc->CS;
  hr=compute_original(d,&copy,iid,out);
 }
 if(SUCCEEDED(hr)&&replacement)scale_capture_unet(d,desc,h,*out,f4q?form:pk?".fp16":"");
 free(replacement);
 if(SUCCEEDED(hr)&&f4q)f4q_note_pipeline(*out,h,loaded,form);
 if(SUCCEEDED(hr)&&pk)fp16_line("FP16_REPLACE",h,loaded,"");
 if(SUCCEEDED(hr))fq_capture(d,desc,h,*out);
 return hr;
}

/* ---- the check's tracking tables */
static struct fq_view *fq_view_slot(SIZE_T cpu,int create){
 UINT i=(UINT)((cpu>>3)*0x9e3779b1u)%FQ_VIEWS;
 for(UINT n=0;n<FQ_VIEWS;n++,i=(i+1)%FQ_VIEWS){
  if(fq_views[i].cpu==cpu)return &fq_views[i];
  if(!fq_views[i].cpu){if(!create)return NULL;fq_views[i].cpu=cpu;return &fq_views[i];}
 }
 return NULL;
}
static void fq_view_set(SIZE_T cpu,UINT kind,ID3D12Resource*r,const void*desc){
 struct fq_view*v=fq_view_slot(cpu,kind!=FQV_NONE&&r!=NULL);if(!v)return;
 v->kind=r?kind:FQV_NONE;v->r=r;v->has_desc=r&&desc;
 if(r&&desc){if(kind==FQV_SRV)v->d.srv=*(const D3D12_SHADER_RESOURCE_VIEW_DESC*)desc;else v->d.uav=*(const D3D12_UNORDERED_ACCESS_VIEW_DESC*)desc;}
}
static void fq_view_copy(SIZE_T dst,SIZE_T src){
 struct fq_view*s=fq_view_slot(src,0);
 if(s&&s->r)fq_view_set(dst,s->kind,s->r,s->has_desc?(const void*)&s->d:NULL);else fq_view_set(dst,FQV_NONE,NULL,NULL);
}
static struct fq_list *fq_list_of(ID3D12GraphicsCommandList*l){
 for(UINT i=0;i<fq_list_count;i++)if(fq_lists[i].l==l)return &fq_lists[i];
 if(fq_list_count==FQ_LISTS)return NULL;
 struct fq_list*s=&fq_lists[fq_list_count++];memset(s,0,sizeof(*s));s->l=l;return s;
}
static struct fq_root *fq_root_of(ID3D12RootSignature*r){for(UINT i=0;i<fq_root_count;i++)if(fq_roots[i].r==r)return &fq_roots[i];return NULL;}
static int fq_resolve(UINT64 gpu,SIZE_T*cpu){
 for(UINT i=fq_heap_count;i-->0;){UINT64 b=fq_heaps[i].gpu,n=(UINT64)fq_heaps[i].count*fq_stride;
  if(gpu>=b&&gpu-b<n){*cpu=fq_heaps[i].cpu+(SIZE_T)(gpu-b);return 1;}}
 return 0;
}

/* ---- device hooks */
static HRESULT STDMETHODCALLTYPE fq_create_root_hook(ID3D12Device*d,UINT node,const void*data,SIZE_T size,REFIID iid,void**out){
 HRESULT hr=fq_next_create_root(d,node,data,size,iid,out);
 if(FAILED(hr)||!out||!*out)return hr;
 HRESULT(WINAPI*deserialize)(const void*,SIZE_T,REFIID,void**)=(void*)GetProcAddress(GetModuleHandleA("d3d12.dll"),"D3D12CreateVersionedRootSignatureDeserializer");
 ID3D12VersionedRootSignatureDeserializer*reader=NULL;const D3D12_VERSIONED_ROOT_SIGNATURE_DESC*desc=NULL;
 if(!deserialize||FAILED(deserialize(data,size,&IID_ID3D12VersionedRootSignatureDeserializer,(void**)&reader)))return hr;
 if(SUCCEEDED(ID3D12VersionedRootSignatureDeserializer_GetRootSignatureDescAtVersion(reader,D3D_ROOT_SIGNATURE_VERSION_1_0,&desc))){
  const D3D12_ROOT_SIGNATURE_DESC*s=&desc->Desc_1_0;
  AcquireSRWLockExclusive(&fq_lock);
  struct fq_root*e=fq_root_of(*out);
  if(!e&&fq_root_count<FQ_ROOTS)e=&fq_roots[fq_root_count++];
  if(e){memset(e,0,sizeof(*e));e->r=*out;e->nparams=s->NumParameters<FQ_PARAMS?s->NumParameters:FQ_PARAMS;
   for(UINT i=0;i<e->nparams;i++){
    if(s->pParameters[i].ParameterType!=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE)continue;
    const D3D12_ROOT_DESCRIPTOR_TABLE*t=&s->pParameters[i].DescriptorTable;UINT cursor=0;
    e->p[i].table=1;e->p[i].nranges=t->NumDescriptorRanges<FQ_RANGES?t->NumDescriptorRanges:FQ_RANGES;
    for(UINT k=0;k<e->p[i].nranges;k++){
     const D3D12_DESCRIPTOR_RANGE*v=&t->pDescriptorRanges[k];
     UINT start=v->OffsetInDescriptorsFromTableStart==D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND?cursor:v->OffsetInDescriptorsFromTableStart;
     e->p[i].ranges[k].type=v->RangeType;e->p[i].ranges[k].count=v->NumDescriptors;e->p[i].ranges[k].offset=start;
     cursor=v->NumDescriptors==UINT_MAX?start:start+v->NumDescriptors;
    }
   }
  }
  ReleaseSRWLockExclusive(&fq_lock);
 }
 ID3D12VersionedRootSignatureDeserializer_Release(reader);
 return hr;
}
static void STDMETHODCALLTYPE fq_uav_hook(ID3D12Device*d,ID3D12Resource*r,ID3D12Resource*counter,const D3D12_UNORDERED_ACCESS_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){
 AcquireSRWLockExclusive(&fq_lock);fq_view_set(h.ptr,FQV_UAV,r,desc);ReleaseSRWLockExclusive(&fq_lock);fq_next_uav(d,r,counter,desc,h);
}
static void STDMETHODCALLTYPE fq_srv_hook(ID3D12Device*d,ID3D12Resource*r,const D3D12_SHADER_RESOURCE_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){
 AcquireSRWLockExclusive(&fq_lock);fq_view_set(h.ptr,FQV_SRV,r,desc);ReleaseSRWLockExclusive(&fq_lock);fq_next_srv(d,r,desc,h);
}
static void STDMETHODCALLTYPE fq_cbv_hook(ID3D12Device*d,const D3D12_CONSTANT_BUFFER_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){
 AcquireSRWLockExclusive(&fq_lock);fq_view_set(h.ptr,FQV_NONE,NULL,NULL);ReleaseSRWLockExclusive(&fq_lock);fq_next_cbv(d,desc,h);
}
static void STDMETHODCALLTYPE fq_copy_simple_hook(ID3D12Device*d,UINT n,D3D12_CPU_DESCRIPTOR_HANDLE dst,D3D12_CPU_DESCRIPTOR_HANDLE src,D3D12_DESCRIPTOR_HEAP_TYPE type){
 if(type==D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV){AcquireSRWLockExclusive(&fq_lock);for(UINT i=0;i<n;i++)fq_view_copy(dst.ptr+(SIZE_T)i*fq_stride,src.ptr+(SIZE_T)i*fq_stride);ReleaseSRWLockExclusive(&fq_lock);}
 fq_next_copy_simple(d,n,dst,src,type);
}
static void STDMETHODCALLTYPE fq_copy_hook(ID3D12Device*d,UINT nd,const D3D12_CPU_DESCRIPTOR_HANDLE*dst,const UINT*dn,UINT ns,const D3D12_CPU_DESCRIPTOR_HANDLE*src,const UINT*sn,D3D12_DESCRIPTOR_HEAP_TYPE type){
 if(type==D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV){
  AcquireSRWLockExclusive(&fq_lock);UINT si=0,so=0;
  for(UINT di=0;di<nd;di++)for(UINT off=0;off<(dn?dn[di]:1);off++){
   if(si>=ns)break;
   fq_view_copy(dst[di].ptr+(SIZE_T)off*fq_stride,src[si].ptr+(SIZE_T)so*fq_stride);
   if(++so==(sn?sn[si]:1)){si++;so=0;}
  }
  ReleaseSRWLockExclusive(&fq_lock);
 }
 fq_next_copy(d,nd,dst,dn,ns,src,sn,type);
}
static HRESULT STDMETHODCALLTYPE fq_heap_hook(ID3D12Device*d,const D3D12_DESCRIPTOR_HEAP_DESC*desc,REFIID iid,void**out){
 HRESULT hr=fq_next_heap(d,desc,iid,out);
 if(SUCCEEDED(hr)&&out&&*out&&desc->Type==D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV&&(desc->Flags&D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE)){
  AcquireSRWLockExclusive(&fq_lock);
  ID3D12DescriptorHeap*h=*out;UINT64 gpu=ID3D12DescriptorHeap_GetGPUDescriptorHandleForHeapStart(h).ptr,span=(UINT64)desc->NumDescriptors*fq_stride;
  UINT k=0;for(UINT i=0;i<fq_heap_count;i++){UINT64 b=fq_heaps[i].gpu,n=(UINT64)fq_heaps[i].count*fq_stride;if(b<gpu+span&&gpu<b+n)continue;fq_heaps[k++]=fq_heaps[i];}
  fq_heap_count=k;
  if(fq_heap_count<FQ_HEAPS){UINT i=fq_heap_count++;fq_heaps[i].h=h;fq_heaps[i].cpu=ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(h).ptr;fq_heaps[i].gpu=gpu;fq_heaps[i].count=desc->NumDescriptors;}
  ReleaseSRWLockExclusive(&fq_lock);
 }
 return hr;
}
/* ---- list hooks: compute root state */
static void STDMETHODCALLTYPE fq_set_root_hook(ID3D12GraphicsCommandList*l,ID3D12RootSignature*r){
 AcquireSRWLockExclusive(&fq_lock);struct fq_list*s=fq_list_of(l);
 if(s&&s->root!=r){memset(s->p,0,sizeof(s->p));s->broken&=~2u;}
 if(s)s->root=r;ReleaseSRWLockExclusive(&fq_lock);fq_next_set_root(l,r);
}
static void fq_note(ID3D12GraphicsCommandList*l,UINT index,UINT kind,UINT64 v){
 AcquireSRWLockExclusive(&fq_lock);struct fq_list*s=fq_list_of(l);
 if(s){if(index>=FQ_PARAMS)s->broken|=2u;else{s->p[index].kind=kind;s->p[index].v=v;if(kind!=2)s->p[index].cmask=0;}}
 ReleaseSRWLockExclusive(&fq_lock);
}
static void STDMETHODCALLTYPE fq_table_hook(ID3D12GraphicsCommandList*l,UINT i,D3D12_GPU_DESCRIPTOR_HANDLE h){fq_note(l,i,1,h.ptr);fq_next_table(l,i,h);}
static void STDMETHODCALLTYPE fq_root_cbv_hook(ID3D12GraphicsCommandList*l,UINT i,D3D12_GPU_VIRTUAL_ADDRESS a){fq_note(l,i,3,a);fq_next_root_cbv(l,i,a);}
static void STDMETHODCALLTYPE fq_root_srv_hook(ID3D12GraphicsCommandList*l,UINT i,D3D12_GPU_VIRTUAL_ADDRESS a){fq_note(l,i,4,a);fq_next_root_srv(l,i,a);}
static void STDMETHODCALLTYPE fq_root_uav_hook(ID3D12GraphicsCommandList*l,UINT i,D3D12_GPU_VIRTUAL_ADDRESS a){fq_note(l,i,5,a);fq_next_root_uav(l,i,a);}
static void fq_note_constants(ID3D12GraphicsCommandList*l,UINT index,UINT count,const UINT*values,UINT offset){
 AcquireSRWLockExclusive(&fq_lock);struct fq_list*s=fq_list_of(l);
 if(s){
  if(index>=FQ_PARAMS||offset>64||count>64-offset)s->broken|=2u;
  else{if(s->p[index].kind!=2){s->p[index].kind=2;s->p[index].cmask=0;}
   for(UINT n=0;n<count;n++){s->p[index].c[offset+n]=values[n];s->p[index].cmask|=1ull<<(offset+n);}}
 }
 ReleaseSRWLockExclusive(&fq_lock);
}
static void STDMETHODCALLTYPE fq_constants_hook(ID3D12GraphicsCommandList*l,UINT i,UINT n,const void*v,UINT o){fq_note_constants(l,i,n,v,o);fq_next_constants(l,i,n,v,o);}
static void STDMETHODCALLTYPE fq_constant_hook(ID3D12GraphicsCommandList*l,UINT i,UINT v,UINT o){fq_note_constants(l,i,1,&v,o);fq_next_constant(l,i,v,o);}
static void STDMETHODCALLTYPE fq_heaps_hook(ID3D12GraphicsCommandList*l,UINT n,ID3D12DescriptorHeap*const*h){
 AcquireSRWLockExclusive(&fq_lock);struct fq_list*s=fq_list_of(l);
 if(s){if(n>2)s->broken|=1u;else{s->nheaps=n;for(UINT i=0;i<n;i++)s->heaps[i]=h[i];s->broken&=~1u;}}
 ReleaseSRWLockExclusive(&fq_lock);fq_next_heaps(l,n,h);
}
static HRESULT STDMETHODCALLTYPE fq_reset_hook(ID3D12GraphicsCommandList*l,ID3D12CommandAllocator*a,ID3D12PipelineState*p){
 HRESULT hr=fq_next_reset(l,a,p);
 if(SUCCEEDED(hr)){AcquireSRWLockExclusive(&fq_lock);struct fq_list*s=fq_list_of(l);if(s){ID3D12GraphicsCommandList*keep=s->l;memset(s,0,sizeof(*s));s->l=keep;}ReleaseSRWLockExclusive(&fq_lock);}
 return hr;
}

/* ---- own objects */
static ID3D12PipelineState*fq_pipeline(const char*name){
 char path[1400];snprintf(path,sizeof(path),"%s\\%s",patchdir,name);FILE*f=fopen(path,"rb");if(!f)return NULL;
 fseek(f,0,SEEK_END);long length=ftell(f);rewind(f);if(length<=0||length>4*1024*1024){fclose(f);return NULL;}
 void*bytes=malloc((size_t)length);if(!bytes||fread(bytes,1,(size_t)length,f)!=(size_t)length){fclose(f);free(bytes);return NULL;}fclose(f);
 D3D12_COMPUTE_PIPELINE_STATE_DESC d={.pRootSignature=fq_root_sig,.CS={bytes,(SIZE_T)length}};ID3D12PipelineState*p=NULL;
 HRESULT hr=compute_original(fq_device,&d,&IID_ID3D12PipelineState,(void**)&p);free(bytes);return SUCCEEDED(hr)?p:NULL;
}
static ID3D12Resource*fq_buffer(UINT64 bytes,D3D12_HEAP_TYPE type){
 D3D12_HEAP_PROPERTIES hp={.Type=type,.CreationNodeMask=1,.VisibleNodeMask=1};
 D3D12_RESOURCE_DESC rd={.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER,.Width=bytes,.Height=1,.DepthOrArraySize=1,.MipLevels=1,.SampleDesc={1,0},
  .Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR,.Flags=type==D3D12_HEAP_TYPE_DEFAULT?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_NONE};
 ID3D12Resource*r=NULL;
 __typeof__(((ID3D12DeviceVtbl*)0)->CreateCommittedResource) create=FQ_INNER(model_committed_original,fq_device->lpVtbl->CreateCommittedResource);
 HRESULT hr=create(fq_device,&hp,D3D12_HEAP_FLAG_NONE,&rd,type==D3D12_HEAP_TYPE_DEFAULT?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:D3D12_RESOURCE_STATE_COPY_DEST,NULL,&IID_ID3D12Resource,(void**)&r);
 return SUCCEEDED(hr)?r:NULL;
}
static D3D12_CPU_DESCRIPTOR_HANDLE fq_cpu(UINT i){D3D12_CPU_DESCRIPTOR_HANDLE h={ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(fq_heap).ptr+(SIZE_T)i*fq_stride};return h;}
static D3D12_GPU_DESCRIPTOR_HANDLE fq_gpu(UINT i){D3D12_GPU_DESCRIPTOR_HANDLE h={ID3D12DescriptorHeap_GetGPUDescriptorHandleForHeapStart(fq_heap).ptr+(UINT64)i*fq_stride};return h;}
static int fq_objects(void){
 if(fq_objects_tried){int ok=fq_root_sig&&fq_heap&&fq_slots&&fq_counters&&fq_readback&&fq_rb;for(UINT i=0;i<FQ_PSOS;i++)ok=ok&&fq_pso[i];return ok;}
 fq_objects_tried=1;
 D3D12_DESCRIPTOR_RANGE ranges[3]={{.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_SRV,.NumDescriptors=1,.BaseShaderRegister=0},
                                   {.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_UAV,.NumDescriptors=1,.BaseShaderRegister=0},
                                   {.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_UAV,.NumDescriptors=2,.BaseShaderRegister=1}};
 D3D12_ROOT_PARAMETER params[4]={{.ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE,.DescriptorTable={1,&ranges[0]},.ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL},
                                 {.ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE,.DescriptorTable={1,&ranges[1]},.ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL},
                                 {.ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE,.DescriptorTable={1,&ranges[2]},.ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL},
                                 {.ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS,.Constants={0,0,16},.ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL}};
 D3D12_ROOT_SIGNATURE_DESC rs={4,params,0,NULL,D3D12_ROOT_SIGNATURE_FLAG_NONE};
 HRESULT(WINAPI*serialize)(const D3D12_ROOT_SIGNATURE_DESC*,D3D_ROOT_SIGNATURE_VERSION,ID3DBlob**,ID3DBlob**)=(void*)GetProcAddress(GetModuleHandleA("d3d12.dll"),"D3D12SerializeRootSignature");
 ID3DBlob*blob=NULL;
 if(!serialize||FAILED(serialize(&rs,D3D_ROOT_SIGNATURE_VERSION_1_0,&blob,NULL)))return 0;
 __typeof__(fq_next_create_root) create_root=FQ_INNER(model_create_root_original,fq_next_create_root);
 HRESULT hr=create_root(fq_device,0,ID3D10Blob_GetBufferPointer(blob),ID3D10Blob_GetBufferSize(blob),&IID_ID3D12RootSignature,(void**)&fq_root_sig);
 ID3D10Blob_Release(blob);if(FAILED(hr)){fq_root_sig=NULL;return 0;}
 for(UINT i=0;i<FQ_PSOS;i++)fq_pso[i]=fq_pipeline(fq_pso_names[i]);
 D3D12_DESCRIPTOR_HEAP_DESC hd={.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,.NumDescriptors=FQ_DESC_BASE+FQ_DESC,.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE};
 __typeof__(fq_next_heap) create_heap=FQ_INNER(model_heap_original,fq_next_heap);
 if(FAILED(create_heap(fq_device,&hd,&IID_ID3D12DescriptorHeap,(void**)&fq_heap)))fq_heap=NULL;
 fq_slots=fq_buffer((UINT64)FQ_SLOTS*16,D3D12_HEAP_TYPE_DEFAULT);fq_counters=fq_buffer((UINT64)FQ_WORDS*4,D3D12_HEAP_TYPE_DEFAULT);
 fq_readback=fq_buffer((UINT64)FQ_RB*FQ_WORDS*4,D3D12_HEAP_TYPE_READBACK);
 if(fq_readback){void*map=NULL;D3D12_RANGE all={0,(SIZE_T)FQ_RB*FQ_WORDS*4};if(SUCCEEDED(ID3D12Resource_Map(fq_readback,0,&all,&map)))fq_rb=map;}
 if(!fq_heap||!fq_slots||!fq_counters)return 0;
 __typeof__(fq_next_uav) make_uav=FQ_INNER(model_uav_original,fq_next_uav);
 __typeof__(fq_next_srv) make_srv=FQ_INNER(model_srv_original,fq_next_srv);
 D3D12_SHADER_RESOURCE_VIEW_DESC ns={.Format=DXGI_FORMAT_R32_UINT,.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2DARRAY,.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING};
 ns.Texture2DArray.MipLevels=1;ns.Texture2DArray.ArraySize=1;make_srv(fq_device,NULL,&ns,fq_cpu(0));
 D3D12_UNORDERED_ACCESS_VIEW_DESC nu={.Format=DXGI_FORMAT_R32_UINT,.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2DARRAY};nu.Texture2DArray.ArraySize=1;
 make_uav(fq_device,NULL,NULL,&nu,fq_cpu(1));
 D3D12_UNORDERED_ACCESS_VIEW_DESC b={.Format=DXGI_FORMAT_R32_TYPELESS,.ViewDimension=D3D12_UAV_DIMENSION_BUFFER};b.Buffer.Flags=D3D12_BUFFER_UAV_FLAG_RAW;
 b.Buffer.NumElements=FQ_SLOTS*4;make_uav(fq_device,fq_slots,NULL,&b,fq_cpu(2));
 b.Buffer.NumElements=FQ_WORDS;make_uav(fq_device,fq_counters,NULL,&b,fq_cpu(3));
 return fq_objects();
}

/* ---- targets: the dispatch's UAV views, with an own descriptor each */
static int fq_fmt_kind(DXGI_FORMAT f){
 switch(f){
 case DXGI_FORMAT_R32G32B32A32_UINT:case DXGI_FORMAT_R32G32B32_UINT:case DXGI_FORMAT_R16G16B16A16_UINT:case DXGI_FORMAT_R32G32_UINT:
 case DXGI_FORMAT_R10G10B10A2_UINT:case DXGI_FORMAT_R8G8B8A8_UINT:case DXGI_FORMAT_R16G16_UINT:case DXGI_FORMAT_R32_UINT:
 case DXGI_FORMAT_R8G8_UINT:case DXGI_FORMAT_R16_UINT:case DXGI_FORMAT_R8_UINT:return 0;
 case DXGI_FORMAT_R32G32B32A32_SINT:case DXGI_FORMAT_R32G32B32_SINT:case DXGI_FORMAT_R16G16B16A16_SINT:case DXGI_FORMAT_R32G32_SINT:
 case DXGI_FORMAT_R8G8B8A8_SINT:case DXGI_FORMAT_R16G16_SINT:case DXGI_FORMAT_R32_SINT:case DXGI_FORMAT_R8G8_SINT:
 case DXGI_FORMAT_R16_SINT:case DXGI_FORMAT_R8_SINT:return 2;
 case DXGI_FORMAT_R32G32B32A32_FLOAT:case DXGI_FORMAT_R16G16B16A16_FLOAT:case DXGI_FORMAT_R16G16B16A16_UNORM:case DXGI_FORMAT_R32G32_FLOAT:
 case DXGI_FORMAT_R8G8B8A8_UNORM:case DXGI_FORMAT_R16G16_FLOAT:case DXGI_FORMAT_R32_FLOAT:case DXGI_FORMAT_R16_FLOAT:case DXGI_FORMAT_R8_UNORM:return 1;
 default:return -1;
 }
}
static UINT fq_fmt_bytes(DXGI_FORMAT f){
 switch(f){case DXGI_FORMAT_R32G32B32A32_UINT:case DXGI_FORMAT_R32G32B32A32_SINT:case DXGI_FORMAT_R32G32B32A32_FLOAT:return 16;
 case DXGI_FORMAT_R32G32_UINT:case DXGI_FORMAT_R32G32_SINT:case DXGI_FORMAT_R32G32_FLOAT:case DXGI_FORMAT_R16G16B16A16_UINT:
 case DXGI_FORMAT_R16G16B16A16_SINT:case DXGI_FORMAT_R16G16B16A16_FLOAT:return 8;
 case DXGI_FORMAT_R32_UINT:case DXGI_FORMAT_R32_SINT:case DXGI_FORMAT_R32_FLOAT:case DXGI_FORMAT_R32_TYPELESS:case DXGI_FORMAT_R8G8B8A8_UINT:
 case DXGI_FORMAT_R8G8B8A8_UNORM:case DXGI_FORMAT_R16G16_FLOAT:return 4;
 default:return 0;}
}
static int fq_is_model(ID3D12Resource*r){for(UINT i=0;i<FQ_MODEL_COUNT();i++)if(FQ_MODEL_R(i)==r)return 1;return 0;}
static int fq_desc(struct fq_target*t){
 uint64_t key=fq_fnv(FQ_FNV0,&t->r,sizeof(t->r));UINT parts[7]={t->kind,t->fmt,t->mip,t->first,t->s,(UINT)t->bytes_begin,(UINT)(t->words+t->off)};
 key=fq_fnv(key,parts,sizeof(parts));
 for(UINT i=0;i<fq_ndesc;i++)if(fq_descs[i].key==key&&fq_descs[i].r==t->r){t->desc=FQ_DESC_BASE+i;return 1;}
 if(fq_ndesc==FQ_DESC)return 0;
 UINT i=fq_ndesc++;fq_descs[i].key=key;fq_descs[i].r=t->r;ID3D12Resource_AddRef(t->r);t->desc=FQ_DESC_BASE+i;
 __typeof__(fq_next_uav) make_uav=FQ_INNER(model_uav_original,fq_next_uav);
 if(t->kind==3){D3D12_UNORDERED_ACCESS_VIEW_DESC v={.Format=DXGI_FORMAT_R32_TYPELESS,.ViewDimension=D3D12_UAV_DIMENSION_BUFFER};
  v.Buffer.FirstElement=t->bytes_begin/4;v.Buffer.NumElements=(UINT)(t->off+t->words);v.Buffer.Flags=D3D12_BUFFER_UAV_FLAG_RAW;make_uav(fq_device,t->r,NULL,&v,fq_cpu(t->desc));}
 else{D3D12_UNORDERED_ACCESS_VIEW_DESC v={.Format=(DXGI_FORMAT)t->fmt,.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2DARRAY};
  v.Texture2DArray.MipSlice=t->mip;v.Texture2DArray.FirstArraySlice=t->first;v.Texture2DArray.ArraySize=t->s;make_uav(fq_device,t->r,NULL,&v,fq_cpu(t->desc));}
 return 1;
}
static int fq_target_of(const struct fq_view*v,struct fq_target*t){
 memset(t,0,sizeof(*t));t->r=v->r;
 D3D12_RESOURCE_DESC rd=ID3D12Resource_GetDesc(v->r);
 if(rd.Dimension==D3D12_RESOURCE_DIMENSION_BUFFER){
  UINT64 begin=0,end=rd.Width;
  if(v->has_desc){
   if(v->d.uav.ViewDimension!=D3D12_UAV_DIMENSION_BUFFER)return 0;
   UINT64 first=v->d.uav.Buffer.FirstElement;UINT count=v->d.uav.Buffer.NumElements,stride=v->d.uav.Buffer.StructureByteStride;
   UINT size=(v->d.uav.Buffer.Flags&D3D12_BUFFER_UAV_FLAG_RAW)?4:stride?stride:fq_fmt_bytes(v->d.uav.Format);
   if(size){begin=first*size;end=begin+(UINT64)count*size;}
   if(end>rd.Width)end=rd.Width;
  }
  if(end<=begin+3)return 0;
  t->bytes_begin=begin&~15ull;t->off=(begin-t->bytes_begin)/4;t->words=(end-begin)/4;t->kind=3;t->w=(UINT)t->words;t->h=1;t->s=1;
  return t->words<=0xffffffffull;
 }
 if(rd.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||rd.SampleDesc.Count>1)return 0;
 DXGI_FORMAT f=rd.Format;UINT mip=0,first=0,count=rd.DepthOrArraySize;
 if(v->has_desc){const D3D12_UNORDERED_ACCESS_VIEW_DESC*u=&v->d.uav;if(u->Format)f=u->Format;
  if(u->ViewDimension==D3D12_UAV_DIMENSION_TEXTURE2D){mip=u->Texture2D.MipSlice;first=0;count=1;}
  else if(u->ViewDimension==D3D12_UAV_DIMENSION_TEXTURE2DARRAY){mip=u->Texture2DArray.MipSlice;first=u->Texture2DArray.FirstArraySlice;count=u->Texture2DArray.ArraySize;}
  else return 0;}
 int k=fq_fmt_kind(f);if(k<0)return 0;
 if(first>=rd.DepthOrArraySize)return 0;if(count==UINT_MAX||first+count>rd.DepthOrArraySize)count=rd.DepthOrArraySize-first;
 t->kind=(UINT)k;t->fmt=f;t->mip=mip;t->first=first;t->s=count;
 t->w=(UINT)(rd.Width>>mip?rd.Width>>mip:1);t->h=rd.Height>>mip?rd.Height>>mip:1;t->words=(UINT64)t->w*t->h*t->s*4;
 return 1;
}
/* the UAV views a dispatch binds (models excluded), under fq_lock */
static void fq_collect(struct fq_list*s,struct fq_root*layout,struct fq_target*set,UINT*n){
 for(UINT p=0;p<layout->nparams&&p<FQ_PARAMS;p++){
  if(!layout->p[p].table||s->p[p].kind!=1)continue;
  for(UINT k=0;k<layout->p[p].nranges;k++){
   if(layout->p[p].ranges[k].type!=D3D12_DESCRIPTOR_RANGE_TYPE_UAV)continue;
   UINT count=layout->p[p].ranges[k].count;if(count==UINT_MAX)count=8;if(count>64)count=64;
   for(UINT j=0;j<count;j++){
    SIZE_T cpu;if(!fq_resolve(s->p[p].v+(UINT64)(layout->p[p].ranges[k].offset+j)*fq_stride,&cpu))continue;
    struct fq_view*v=fq_view_slot(cpu,0);if(!v||!v->r||v->kind!=FQV_UAV||fq_is_model(v->r))continue;
    struct fq_target t;if(!fq_target_of(v,&t)){fq.skips[FQK_UNSUPPORTED]++;continue;}
    if(*n<FQ_SET)set[(*n)++]=t;
   }
  }
 }
}

/* ---- recording own work into the runtime's list */
static __typeof__(fq_next_set_root) fq_set_root_inner;
static __typeof__(fq_next_table) fq_table_inner;
static __typeof__(fq_next_constants) fq_constants_inner;
static void fq_barrier(ID3D12GraphicsCommandList*l){D3D12_RESOURCE_BARRIER b={.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV,.UAV={NULL}};ID3D12GraphicsCommandList_ResourceBarrier(l,1,&b);}
static ID3D12PipelineState*fq_bound_pso(ID3D12GraphicsCommandList*l){ID3D12PipelineState*o=NULL;for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)o=bindings[b].p;return o;}
static int fq_begin(ID3D12GraphicsCommandList*l,uint64_t shader){
 if(!fq_objects()){fq_skip(FQK_OBJECTS,shader);fq.stopped=1;logline("F4Q_STOP own pass objects unavailable (profile files or device)\n");return 0;}
 AcquireSRWLockExclusive(&fq_lock);struct fq_list*s=fq_list_of(l);int ok=s&&!s->broken&&s->root;ReleaseSRWLockExclusive(&fq_lock);
 if(!ok){fq_skip(FQK_LIST,shader);return 0;}
 fq_set_root_inner=FQ_INNER(model_root_original,fq_next_set_root);fq_table_inner=FQ_INNER(model_table_original,fq_next_table);
 fq_constants_inner=FQ_INNER(model_constants_original,fq_next_constants);
 fq_barrier(l);
 ID3D12DescriptorHeap*own[1]={fq_heap};fq_next_heaps(l,1,own);
 fq_set_root_inner(l,fq_root_sig);
 fq_table_inner(l,0,fq_gpu(0));fq_table_inner(l,1,fq_gpu(1));fq_table_inner(l,2,fq_gpu(2));
 return 1;
}
static void fq_end(ID3D12GraphicsCommandList*l){
 fq_barrier(l);
 AcquireSRWLockExclusive(&fq_lock);
 struct fq_list*s=fq_list_of(l);
 if(s->nheaps)fq_next_heaps(l,s->nheaps,s->heaps);
 fq_set_root_inner(l,s->root);
 for(UINT p=0;p<FQ_PARAMS;p++){
  switch(s->p[p].kind){
  case 1:fq_table_inner(l,p,(D3D12_GPU_DESCRIPTOR_HANDLE){s->p[p].v});break;
  case 2:for(UINT o=0;o<64;){if(!(s->p[p].cmask>>o&1)){o++;continue;}UINT e=o;while(e<64&&(s->p[p].cmask>>e&1))e++;fq_constants_inner(l,p,e-o,&s->p[p].c[o],o);o=e;}break;
  case 3:fq_next_root_cbv(l,p,s->p[p].v);break;
  case 4:fq_next_root_srv(l,p,s->p[p].v);break;
  case 5:fq_next_root_uav(l,p,s->p[p].v);break;
  }
 }
 ReleaseSRWLockExclusive(&fq_lock);
 set_original(l,fq_bound_pso(l));
}
static void fq_aux(ID3D12GraphicsCommandList*l,const UINT c[16]){set_original(l,fq_pso[4]);fq_constants_inner(l,3,16,c,0);dispatch_original(l,1,1,1);}
static int fq_fp(ID3D12GraphicsCommandList*l,struct fq_target*t,UINT n,struct fq_batch*b){
 memset(b,0,sizeof(*b));if(!n)return 1;
 for(UINT i=0;i<n;i++)if(!fq_desc(&t[i])){fq_skip(FQK_DESC_FULL,0);fq.stopped=1;logline("F4Q_STOP own descriptor cache full\n");return 0;}
 if(fq.cursor+n>FQ_SLOTS)fq.cursor=0;
 b->base=fq.cursor;b->n=n;b->tag=++fq.tag;fq.cursor+=n;
 UINT clear[16]={0,b->base,n,b->tag};fq_aux(l,clear);fq_barrier(l);
 for(UINT i=0;i<n;i++){
  set_original(l,fq_pso[t[i].kind]);
  fq_table_inner(l,1,fq_gpu(t[i].desc));
  if(t[i].kind==3){UINT64 groups=(t[i].words+1023)/1024;UINT gx=groups<65535?(UINT)groups:65535,gy=(UINT)((groups+gx-1)/gx);
   UINT c[16]={(UINT)t[i].words,(UINT)t[i].off,gx,b->base+i};fq_constants_inner(l,3,16,c,0);dispatch_original(l,gx,gy,1);}
  else{UINT c[16]={t[i].w,t[i].h,t[i].s,b->base+i};fq_constants_inner(l,3,16,c,0);dispatch_original(l,(t[i].w+31)/32,(t[i].h+31)/32,t[i].s);}
  fq_table_inner(l,1,fq_gpu(1));
 }
 return 1;
}
/* GPU comparison of batch a against batch b, counted under point (class: forced "no inputs" = 4) */
static void fq_compare(ID3D12GraphicsCommandList*l,UINT point,const struct fq_batch*a,const struct fq_batch*b){
 UINT c[16]={1,a->base,b->base,a->n, a->tag,b->tag,0,0, 0,0,0,point, 0,2,0,0};
 fq_aux(l,c);
}
static void fq_publish(ID3D12GraphicsCommandList*l,UINT stamp){
 UINT c[16]={2,stamp};fq_aux(l,c);fq_barrier(l);
 D3D12_RESOURCE_BARRIER tr={.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION,.Transition={fq_counters,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE}};
 ID3D12GraphicsCommandList_ResourceBarrier(l,1,&tr);
 __typeof__(((ID3D12GraphicsCommandListVtbl*)0)->CopyBufferRegion) copy=FQ_INNER(model_copy_original,l->lpVtbl->CopyBufferRegion);
 copy(l,fq_readback,(UINT64)(fq_rb_next++%FQ_RB)*FQ_WORDS*4,fq_counters,0,(UINT64)FQ_WORDS*4);
 tr.Transition.StateBefore=D3D12_RESOURCE_STATE_COPY_SOURCE;tr.Transition.StateAfter=D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
 ID3D12GraphicsCommandList_ResourceBarrier(l,1,&tr);
}
/* ---- logging */
static const volatile UINT*fq_latest(UINT*stamp){
 const volatile UINT*best=NULL;*stamp=0;
 if(!fq_rb)return NULL;
 for(UINT r=0;r<FQ_RB;r++){const volatile UINT*c=fq_rb+(size_t)r*FQ_WORDS;UINT h=c[0];MemoryBarrier();UINT t=c[FQ_WORDS-1];if(h&&h==t&&h>*stamp){*stamp=h;best=c;}}
 return best;
}
static void fq_status(const char*why){
 UINT stamp;const volatile UINT*c=fq_latest(&stamp);char line[600];
 snprintf(line,sizeof(line),"F4Q_STATUS why=%s ticks=%ld dispatches=%llu/%llu/%llu compares=%llu stamp=%u stale=%u gpu_compares=%u skips=%llu/%llu/%llu/%llu/%llu/%llu/%llu/%llu/%llu\n",
          why,(long)InterlockedCompareExchange(&fq_ticks,0,0),(unsigned long long)fq.dispatches[0],(unsigned long long)fq.dispatches[1],(unsigned long long)fq.dispatches[2],
          (unsigned long long)fq.compares,stamp,c?c[1]:0,c?c[2]:0,(unsigned long long)fq.skips[0],(unsigned long long)fq.skips[1],(unsigned long long)fq.skips[2],
          (unsigned long long)fq.skips[3],(unsigned long long)fq.skips[4],(unsigned long long)fq.skips[5],(unsigned long long)fq.skips[6],(unsigned long long)fq.skips[7],
          (unsigned long long)fq.skips[8]);
 logline(line);
 if(f4q2_mask){snprintf(line,sizeof(line),"F4Q2_STATUS dispatches=%llu/%llu/%llu (1a3b0782/e83e868f/9e0080ee)\n",
                        (unsigned long long)fq.dispatches[3],(unsigned long long)fq.dispatches[4],(unsigned long long)fq.dispatches[5]);
               logline(line);}
 if(f4q3_mask){snprintf(line,sizeof(line),"F4Q3_STATUS dispatches=%llu/%llu (60edebbb/b3ddf030)\n",(unsigned long long)fq.dispatches[6],
                        (unsigned long long)fq.dispatches[7]);logline(line);}
 /* class 4 = forced "no inputs", same tick 0: counters[PTBASE + (point * 8 + 4) * 2 + {0 equal, 1 differ}] (batches) */
 if(c)for(UINT p=0;p<FQ_POINTS;p++){UINT eq=c[FQ_PTBASE+(p*8+4)*2],ne=c[FQ_PTBASE+(p*8+4)*2+1];
  if(eq||ne){snprintf(line,sizeof(line),"F4Q_COUNT stamp=%u point=%s equal=%u differ=%u\n",stamp,fq_point_names[p],eq,ne);logline(line);}}
}
static void fq_maybe_status(void){
 LONG ticks=InterlockedCompareExchange(&fq_ticks,0,0);
 if(ticks-fq.last_log_tick<(LONG)FQ_LOG_EVERY)return;
 fq.last_log_tick=ticks;fq_status("interval");
}

/* ---- the check (fast_dispatch, under fast_record_lock): before and after each of the runtime's dispatches */
static void fq_before(ID3D12GraphicsCommandList*l,uint64_t shader,UINT x,UINT y,UINT z){
 fq.pending_n=0;
 if(!fq.on||fq.stopped||!fq_target_shader(shader))return;
 ID3D12PipelineState*bound=fq_bound_pso(l),*f4q=NULL;
 AcquireSRWLockExclusive(&fq_lock);
 for(UINT i=0;i<fq_pair_count;i++)if(fq_pairs[i].exact==bound&&fq_pairs[i].hash==shader)f4q=fq_pairs[i].f4q;
 struct fq_list*s=fq_list_of(l);struct fq_root*layout=s&&s->root?fq_root_of(s->root):NULL;
 static struct fq_target t[FQ_SET];UINT n=0;   /* static: calls are serialized (fast_record_lock) */
 if(s&&layout)fq_collect(s,layout,t,&n);
 ReleaseSRWLockExclusive(&fq_lock);
 if(!f4q){fq_skip(FQK_PAIR,shader);return;}
 if(!layout){fq_skip(FQK_ROOT,shader);return;}
 if(n!=1){fq_skip(FQK_TARGETS,shader);return;}
 UINT gx,gy,gz;if(!fq_groups(shader,x,y,z,&gx,&gy,&gz)){fq_skip(FQK_GEOMETRY,shader);return;}
 UINT point=shader==F4Q3_60ED?6:shader==F4Q3_B3DD?7:shader==F4Q2_1A3B?3:shader==F4Q2_E83E?4:shader==F4Q2_9E00?5:
            shader==FQ_ENC?2:t[0].w>=1024?0:1;
 /* 1. the F(4x4) kernel into the output view, with the runtime's root arguments (same root signature) */
 set_original(l,f4q);dispatch_original(l,gx,gy,gz);
 /* 2. its fingerprint; fq_end restores the runtime's state and the bound (exact) pipeline */
 if(!fq_begin(l,shader)){set_original(l,bound);return;}
 int ok=fq_fp(l,t,n,&fq.b);
 fq_end(l);
 if(!ok)return;
 memcpy(fq.t,t,sizeof(*t)*n);fq.pending_n=n;fq.pending_point=point;fq.dispatches[point]++;
}
static void fq_after(ID3D12GraphicsCommandList*l,uint64_t shader){
 if(!fq.on||fq.stopped||!fq.pending_n||!fq_target_shader(shader))return;
 UINT n=fq.pending_n;fq.pending_n=0;
 /* 3. the exact kernel ran (the runtime's dispatch); its fingerprint, then the comparison */
 if(!fq_begin(l,shader))return;
 struct fq_batch a;int ok=fq_fp(l,fq.t,n,&a);
 fq_barrier(l);
 if(ok){fq_compare(l,fq.pending_point,&a,&fq.b);fq.compares++;fq_barrier(l);if(fq.compares%16==0)fq_publish(l,(UINT)fq.compares);}
 fq_end(l);
 fq_maybe_status();
}
/* xefgSwapChainTagFrameConstants (mfg_proxy_coexist.h proxy_frame_tick): one per real frame */
static void fq_frame_tick(void){if(fq.on)InterlockedIncrement(&fq_ticks);}
static void fq_install(ID3D12Device*d,ID3D12GraphicsCommandList*l){
 fq.on=f4q_mode==F4Q_SHADOW;
 if(!fq.on)return;                                       /* the check is off: no tracking hook installed */
 fq_device=d;fq_stride=ID3D12Device_GetDescriptorHandleIncrementSize(d,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 fq_next_create_root=d->lpVtbl->CreateRootSignature;replace((void*)&d->lpVtbl->CreateRootSignature,fq_create_root_hook);
 fq_next_uav=d->lpVtbl->CreateUnorderedAccessView;replace((void*)&d->lpVtbl->CreateUnorderedAccessView,fq_uav_hook);
 fq_next_srv=d->lpVtbl->CreateShaderResourceView;replace((void*)&d->lpVtbl->CreateShaderResourceView,fq_srv_hook);
 fq_next_cbv=d->lpVtbl->CreateConstantBufferView;replace((void*)&d->lpVtbl->CreateConstantBufferView,fq_cbv_hook);
 fq_next_copy_simple=d->lpVtbl->CopyDescriptorsSimple;replace((void*)&d->lpVtbl->CopyDescriptorsSimple,fq_copy_simple_hook);
 fq_next_copy=d->lpVtbl->CopyDescriptors;replace((void*)&d->lpVtbl->CopyDescriptors,fq_copy_hook);
 fq_next_heap=d->lpVtbl->CreateDescriptorHeap;replace((void*)&d->lpVtbl->CreateDescriptorHeap,fq_heap_hook);
 fq_next_set_root=l->lpVtbl->SetComputeRootSignature;replace((void*)&l->lpVtbl->SetComputeRootSignature,fq_set_root_hook);
 fq_next_table=l->lpVtbl->SetComputeRootDescriptorTable;replace((void*)&l->lpVtbl->SetComputeRootDescriptorTable,fq_table_hook);
 fq_next_constant=l->lpVtbl->SetComputeRoot32BitConstant;replace((void*)&l->lpVtbl->SetComputeRoot32BitConstant,fq_constant_hook);
 fq_next_constants=l->lpVtbl->SetComputeRoot32BitConstants;replace((void*)&l->lpVtbl->SetComputeRoot32BitConstants,fq_constants_hook);
 fq_next_root_cbv=l->lpVtbl->SetComputeRootConstantBufferView;replace((void*)&l->lpVtbl->SetComputeRootConstantBufferView,fq_root_cbv_hook);
 fq_next_root_srv=l->lpVtbl->SetComputeRootShaderResourceView;replace((void*)&l->lpVtbl->SetComputeRootShaderResourceView,fq_root_srv_hook);
 fq_next_root_uav=l->lpVtbl->SetComputeRootUnorderedAccessView;replace((void*)&l->lpVtbl->SetComputeRootUnorderedAccessView,fq_root_uav_hook);
 fq_next_heaps=l->lpVtbl->SetDescriptorHeaps;replace((void*)&l->lpVtbl->SetDescriptorHeaps,fq_heaps_hook);
 fq_next_reset=l->lpVtbl->Reset;replace((void*)&l->lpVtbl->Reset,fq_reset_hook);
 logline("F4Q_INSTALLED root, descriptor and heap tracking; shadow compares at b3941ac8 and f030948d\n");
 if(f4q2_mask){char line[160];snprintf(line,sizeof(line),"F4Q2_INSTALLED shadow compares also at the F4Q2 layers %u (points 3..5)\n",f4q2_mask);logline(line);}
 if(f4q3_mask){char line[160];snprintf(line,sizeof(line),"F4Q3_INSTALLED shadow compares also at the F4Q3 row layers %u (points 6..7)\n",f4q3_mask);logline(line);}
}
/* After GPU completion is confirmed (fast_finish), before the fast log closes: the check's last counters, then release of
 * every own object and reference, and this context's F(4x4) pipeline table (fast_finish releases the pipelines). */
static void fq_finish(void){
 memset(f4q_pipelines,0,sizeof(f4q_pipelines));f4q_pipeline_count=0;
 if(fq.on){
  fq_status("release");
  UINT stamp;fq_latest(&stamp);char line[300];
  snprintf(line,sizeof(line),"F4Q_SUMMARY compares=%llu descriptors=%u pairs=%u stamp=%u\n",(unsigned long long)fq.compares,fq_ndesc,fq_pair_count,stamp);logline(line);
 }
 if(fq_readback&&fq_rb){D3D12_RANGE none={0,0};ID3D12Resource_Unmap(fq_readback,0,&none);}fq_rb=NULL;
 for(UINT i=0;i<FQ_PSOS;i++)if(fq_pso[i]){ID3D12PipelineState_Release(fq_pso[i]);fq_pso[i]=NULL;}
 for(UINT i=0;i<fq_pair_count;i++)if(fq_pairs[i].f4q)ID3D12PipelineState_Release(fq_pairs[i].f4q);
 memset(fq_pairs,0,sizeof(fq_pairs));fq_pair_count=0;
 if(fq_root_sig){ID3D12RootSignature_Release(fq_root_sig);fq_root_sig=NULL;}
 if(fq_heap){ID3D12DescriptorHeap_Release(fq_heap);fq_heap=NULL;}
 if(fq_slots){ID3D12Resource_Release(fq_slots);fq_slots=NULL;}
 if(fq_counters){ID3D12Resource_Release(fq_counters);fq_counters=NULL;}
 if(fq_readback){ID3D12Resource_Release(fq_readback);fq_readback=NULL;}
 for(UINT i=0;i<fq_ndesc;i++)ID3D12Resource_Release(fq_descs[i].r);
 fq_ndesc=0;fq_objects_tried=0;fq_rb_next=0;
 memset(fq_lists,0,sizeof(fq_lists));fq_list_count=0;memset(fq_roots,0,sizeof(fq_roots));fq_root_count=0;memset(fq_views,0,sizeof(fq_views));
 memset(fq_heaps,0,sizeof(fq_heaps));fq_heap_count=0;memset(fq_descs,0,sizeof(fq_descs));
 UINT on=fq.on;memset(&fq,0,sizeof(fq));fq.on=on;
 InterlockedExchange(&fq_ticks,0);fq_device=NULL;
}
