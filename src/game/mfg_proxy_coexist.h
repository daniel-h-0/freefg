/* SPDX-License-Identifier: MIT
 * The multi-frame proxy (variant intel-free-mfg, XEFG_PROXY_MFG) beside another module that hooks Intel's XeFG runtime,
 * such as a tool that lifts Intel's frame limit (packaging/public/ARCHITECTURE.md, "Another mod on Intel's runtime").
 * This project patches nothing in Intel's runtime and reads nothing of another module; it only notices that Intel's
 * entry points no longer hold the bytes of the verified file, and then changes its own behaviour:
 *
 *  - Caller kept. Such a module may tell its callers apart by return address (the game, a wrapper such as OptiScaler,
 *    the runtime itself). The lifecycle entries (CreateContext, both InitFromSwapChain forms, Destroy) then tail-call
 *    Intel's entry, so the module sees exactly the caller it would see without this proxy. The work this proxy does
 *    after those calls in the ordinary path moves to the next call that comes after them: after CreateContext, the
 *    handle's first initialisation (or its destruction) claims the scoped device; after InitFromSwapChain, the first
 *    later call that carries the handle (D3D12GetSwapChainPtr, which callers make right after a successful
 *    initialisation, else SetNumInterpolatedFrames, GetLastPresentStatus or TagFrameConstants, always before the call
 *    reaches Intel) seals the model census and builds the network, so the census holds exactly what the initialisation
 *    allocated, as in the ordinary path; after Destroy, the next CreateContext or initialisation releases this proxy's
 *    resources. D3D12GetSwapChainPtr and TagFrameConstants always tail-call. GetLastPresentStatus and
 *    SetNumInterpolatedFrames take the handle first and stay ordinary calls.
 *  - Real objects for contexts this proxy does not accelerate (not a candidate: another GPU, BC250_XEFG_DISABLE=1, a
 *    second context): Intel gets the caller's own device and queue, as without this proxy.
 *  - Only OptiScaler's own contexts are accelerated (created from a module whose version resource names the product
 *    OptiScaler). A game's own XeFG context (FreeFG's native route) keeps the game's device: such a module may follow a
 *    game's own contexts and compare the device Intel is given with the device of the game's queue and swap chain, and
 *    the scoped device this proxy would hand Intel is a forwarding object that never matches, so frame generation
 *    would not start at all. That context then runs Intel's (or that module's) shaders at every frame count.
 *  - Our shaders where Intel's runtime still creates Intel's programs: a context this proxy accelerates keeps the
 *    by-hash replacements at every frame count. The pipelines it replaces are paired with Intel's original pipelines,
 *    created alongside, so it can step aside at any later point.
 *  - Stepping aside instead of closing the game: when the model census or the order of the network's work is not one
 *    this project verified (another module's own network, or programs it swapped in), the context steps aside once:
 *    its device, command-list and queue tables return to plain forwarding, every replaced pipeline is bound as Intel's
 *    original from then on, and the network, census and dispatch checks stop. One FAST_ASIDE line in BC250-MFG.log and
 *    BC250-XeFG-fast.log says why. Without another module every check stays fatal, as in the 2x build.
 */
#define PROXY_PROLOGUE 16
static const char*const proxy_watched[]={
 "xefgSwapChainD3D12CreateContext","xefgSwapChainD3D12InitFromSwapChain","xefgSwapChainD3D12InitFromSwapChainDesc",
 "xefgSwapChainDestroy","xefgSwapChainGetLastPresentStatus","xefgSwapChainSetNumInterpolatedFrames",
 "xefgSwapChainTagFrameConstants","xefgSwapChainGetProperties"};
#define PROXY_WATCHED (sizeof(proxy_watched)/sizeof(*proxy_watched))
static struct{DWORD rva;unsigned char bytes[PROXY_PROLOGUE],mask[PROXY_PROLOGUE];} proxy_entries[PROXY_WATCHED];
static int proxy_entries_known;

/* ------------------------------------------------------------------------------------------- the verified file */

static int proxy_read_at(HANDLE f,DWORD offset,void*out,DWORD size){
 OVERLAPPED at={0};at.Offset=offset;DWORD n=0;return ReadFile(f,out,size,&n,&at)&&n==size;
}
struct proxy_section{DWORD virtual_size,address,raw_size,raw;};
static int proxy_offset(const struct proxy_section*s,UINT count,DWORD rva,DWORD size,DWORD*offset){
 for(UINT i=0;i<count;i++){DWORD span=s[i].raw_size<s[i].virtual_size?s[i].raw_size:s[i].virtual_size;
  if(rva>=s[i].address&&rva-s[i].address<span&&size<=span-(rva-s[i].address)){*offset=s[i].raw+(rva-s[i].address);return 1;}}
 return 0;
}
/* Called once, after the verified runtime has loaded: the RVA of each watched export and the first bytes of its code,
 * read from bc250_xefg_original.dll on disk (never from memory, which another module may already have changed), with
 * the bytes base relocations would rewrite masked out. Without this table every context runs as without another module
 * (its CreateContext logs why once). */
static void proxy_snapshot_entries(const wchar_t*path){
 HANDLE f=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);if(f==INVALID_HANDLE_VALUE)return;
 static unsigned char header[4096];struct proxy_section sections[32];  /* static: called once (mfg_initialize), and no stack probe without the CRT */
 UINT count=0;int ok=proxy_read_at(f,0,header,sizeof(header));
 DWORD pe=ok?*(DWORD*)(header+0x3c):0;
 ok=ok&&pe<sizeof(header)-264&&!memcmp(header+pe,"PE\0\0",4)&&*(WORD*)(header+pe+24)==0x20b;
 DWORD optional=pe+24,export_rva=0,export_size=0,reloc_rva=0,reloc_size=0;
 if(ok){
  count=*(WORD*)(header+pe+6);DWORD table=optional+*(WORD*)(header+pe+20);
  export_rva=*(DWORD*)(header+optional+112);export_size=*(DWORD*)(header+optional+116);
  reloc_rva=*(DWORD*)(header+optional+152);reloc_size=*(DWORD*)(header+optional+156);
  ok=count&&count<=32&&table+40*count<=sizeof(header)&&export_rva&&export_size>=40;
  for(UINT i=0;ok&&i<count;i++){unsigned char*s=header+table+40*i;
   sections[i].virtual_size=*(DWORD*)(s+8);sections[i].address=*(DWORD*)(s+12);sections[i].raw_size=*(DWORD*)(s+16);sections[i].raw=*(DWORD*)(s+20);}
 }
 DWORD at=0;unsigned char directory[40];
 ok=ok&&proxy_offset(sections,count,export_rva,40,&at)&&proxy_read_at(f,at,directory,40);
 DWORD functions=ok?*(DWORD*)(directory+20):0,names=ok?*(DWORD*)(directory+24):0;
 ok=ok&&functions&&functions<=4096&&names&&names<=4096;
 DWORD*function_rvas=ok?HeapAlloc(GetProcessHeap(),0,functions*4):NULL,*name_rvas=ok?HeapAlloc(GetProcessHeap(),0,names*4):NULL;
 WORD*ordinals=ok?HeapAlloc(GetProcessHeap(),0,names*2):NULL;
 ok=ok&&function_rvas&&name_rvas&&ordinals
  &&proxy_offset(sections,count,*(DWORD*)(directory+28),functions*4,&at)&&proxy_read_at(f,at,function_rvas,functions*4)
  &&proxy_offset(sections,count,*(DWORD*)(directory+32),names*4,&at)&&proxy_read_at(f,at,name_rvas,names*4)
  &&proxy_offset(sections,count,*(DWORD*)(directory+36),names*2,&at)&&proxy_read_at(f,at,ordinals,names*2);
 UINT found=0;
 for(DWORD i=0;ok&&i<names;i++){
  char name[64]={0};if(!proxy_offset(sections,count,name_rvas[i],1,&at)||!proxy_read_at(f,at,name,sizeof(name)-1)){
   /* a name near the end of its section: read what the section holds */
   DWORD n=0;for(;n<sizeof(name)-1;n++)if(!proxy_offset(sections,count,name_rvas[i]+n,1,&at)||!proxy_read_at(f,at,name+n,1))break;
   name[n]=0;}
  for(UINT w=0;w<PROXY_WATCHED;w++)if(!strcmp(name,proxy_watched[w])&&ordinals[i]<functions){
   DWORD rva=function_rvas[ordinals[i]];
   if(rva>=export_rva&&rva-export_rva<export_size){ok=0;break;}  /* a forwarder: not the runtime this proxy was written for */
   if(!proxy_offset(sections,count,rva,PROXY_PROLOGUE,&at)||!proxy_read_at(f,at,proxy_entries[w].bytes,PROXY_PROLOGUE)){ok=0;break;}
   proxy_entries[w].rva=rva;found++;
  }
 }
 /* Base relocations (IMAGE_REL_BASED_DIR64, type 10) inside a watched window change with the load address. */
 if(ok&&reloc_rva&&reloc_size&&reloc_size<=1u<<20){
  unsigned char*relocs=HeapAlloc(GetProcessHeap(),0,reloc_size);
  if(relocs&&proxy_offset(sections,count,reloc_rva,reloc_size,&at)&&proxy_read_at(f,at,relocs,reloc_size)){
   for(DWORD block=0;block+8<=reloc_size;){DWORD page=*(DWORD*)(relocs+block),size=*(DWORD*)(relocs+block+4);if(size<8||size>reloc_size-block)break;
    for(DWORD e=block+8;e+2<=block+size;e+=2){WORD entry=*(WORD*)(relocs+e);if(entry>>12!=10)continue;DWORD target=page+(entry&0xfff);
     for(UINT w=0;w<PROXY_WATCHED;w++)for(UINT b=0;b<PROXY_PROLOGUE;b++)if(target<=proxy_entries[w].rva+b&&proxy_entries[w].rva+b<target+8)proxy_entries[w].mask[b]=1;}
    block+=size;}
  }else ok=0;
  if(relocs)HeapFree(GetProcessHeap(),0,relocs);
 }
 if(function_rvas)HeapFree(GetProcessHeap(),0,function_rvas);if(name_rvas)HeapFree(GetProcessHeap(),0,name_rvas);if(ordinals)HeapFree(GetProcessHeap(),0,ordinals);
 CloseHandle(f);
 proxy_entries_known=ok&&found==PROXY_WATCHED;
}

/* ---------------------------------------------------------------------------------------------- hook detection */

/* The module that owns code at an address, following up to two jumps (rel32, or through a RIP-relative pointer) the
 * way an inline hook's patch and its relay are written; for the log only. */
static void proxy_jump_owner(const unsigned char*code,char*out,size_t size){
 const unsigned char*p=code;
 for(int hop=0;hop<3;hop++){
  HMODULE m=NULL;
  if(GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,(const char*)p,&m)&&m!=original_module){
   char path[MAX_PATH];DWORD n=GetModuleFileNameA(m,path,sizeof(path));const char*leaf=n?strrchr(path,'\\'):NULL;
   snprintf(out,size,"%s",leaf?leaf+1:n?path:"an unnamed module");return;}
  MEMORY_BASIC_INFORMATION info;if(!VirtualQuery(p,&info,sizeof(info))||info.State!=MEM_COMMIT||(info.Protect&(PAGE_NOACCESS|PAGE_GUARD)))break;
  if(p[0]==0xe9)p=p+5+*(const INT32*)(p+1);
  else if(p[0]==0xff&&p[1]==0x25){const unsigned char*slot=p+6+*(const INT32*)(p+2);if(!VirtualQuery(slot,&info,sizeof(info))||info.State!=MEM_COMMIT)break;p=*(const unsigned char*const*)slot;}
  else break;
 }
 snprintf(out,size,"code outside any loaded module");
}
static volatile LONG proxy_foreign_seen;  /* the last answer, for logging changes only */
/* Whether another module has hooked Intel's XeFG runtime: a watched entry's code differs from the verified file, or
 * GetProcAddress no longer returns the export's address. Read at every CreateContext, initialisation and destruction
 * (rare calls); a change is logged once. */
static int proxy_foreign_hooks(void){
 if(!proxy_entries_known){static LONG told;if(!InterlockedExchange(&told,1))proxy_log("FAST_COEXIST the runtime's entry table could not be read from bc250_xefg_original.dll; hooks by other modules are not detected\n");return 0;}
 const unsigned char*base=(const unsigned char*)original_module;int hooked=-1;const char*how="";
 for(UINT w=0;w<PROXY_WATCHED&&hooked<0;w++){
  const unsigned char*entry=base+proxy_entries[w].rva;
  for(UINT b=0;b<PROXY_PROLOGUE;b++)if(!proxy_entries[w].mask[b]&&entry[b]!=proxy_entries[w].bytes[b]){hooked=(int)w;how="its code was changed";break;}
  if(hooked<0&&(const unsigned char*)GetProcAddress(original_module,proxy_watched[w])!=entry){hooked=(int)w;how="GetProcAddress returns another address";}
 }
 LONG now=hooked>=0;
 if(InterlockedExchange(&proxy_foreign_seen,now)!=now){
  char line[400];
  if(now){char owner[160];const unsigned char*code=base+proxy_entries[hooked].rva;
   if(*how=='G')code=(const unsigned char*)GetProcAddress(original_module,proxy_watched[hooked]);
   proxy_jump_owner(code,owner,sizeof(owner));
   snprintf(line,sizeof(line),"FAST_COEXIST another module hooks Intel's XeFG runtime (%s: %s; jumps to %s): lifecycle calls keep their caller, "
            "unrecognised work steps aside instead of ending the game\n",proxy_watched[hooked],how,owner);}
  else snprintf(line,sizeof(line),"FAST_COEXIST Intel's XeFG entries match the verified file again\n");
  proxy_log(line);
 }
 return now;
}

/* ------------------------------------------------------------------------------------------- OptiScaler's contexts */

/* One node of a version resource (VS_VERSIONINFO and its children): wLength, wValueLength (in WCHARs for a text value),
 * wType, the key (UTF-16, NUL-terminated), the value and the children, each aligned to 4 bytes from the resource's
 * start. */
struct proxy_node{const WCHAR*key;const unsigned char*value,*children,*end;WORD type,value_length;};
static int proxy_node_at(const unsigned char*base,const unsigned char*p,const unsigned char*limit,struct proxy_node*n){
 if(limit-p<6)return 0;
 WORD length=*(const WORD*)p;if(length<6||length>limit-p)return 0;
 n->end=p+length;n->value_length=((const WORD*)p)[1];n->type=((const WORD*)p)[2];n->key=(const WCHAR*)(p+6);
 const unsigned char*q=p+6;while(n->end-q>=2&&*(const WCHAR*)q)q+=2;if(n->end-q<2)return 0;q+=2;
 q=base+((q-base+3)&~(ptrdiff_t)3);if(q>n->end)q=n->end;n->value=q;
 size_t bytes=n->type==1?(size_t)n->value_length*2:n->value_length;if(bytes>(size_t)(n->end-q))bytes=n->end-q;
 q+=bytes;q=base+((q-base+3)&~(ptrdiff_t)3);n->children=q>n->end?n->end:q;
 return 1;
}
static const unsigned char*proxy_node_next(const unsigned char*base,const struct proxy_node*n){return base+((n->end-base+3)&~(ptrdiff_t)3);}
/* Whether a module's version resource has StringFileInfo/<any table>/ProductName "OptiScaler" (any letter case). */
static int proxy_module_is_optiscaler(HMODULE module){
 HRSRC found=module?FindResourceW(module,MAKEINTRESOURCEW(1),MAKEINTRESOURCEW(16)):NULL;  /* VS_VERSION_INFO, RT_VERSION */
 HGLOBAL loaded=found?LoadResource(module,found):NULL;DWORD size=found?SizeofResource(module,found):0;
 const unsigned char*base=loaded?LockResource(loaded):NULL;if(!base||size<6)return 0;
 const unsigned char*limit=base+size;struct proxy_node root,block,table,string;
 if(!proxy_node_at(base,base,limit,&root)||lstrcmpW(root.key,L"VS_VERSION_INFO"))return 0;
 for(const unsigned char*p=root.children;p<root.end&&proxy_node_at(base,p,root.end,&block);p=proxy_node_next(base,&block)){
  if(lstrcmpW(block.key,L"StringFileInfo"))continue;
  for(const unsigned char*t=block.children;t<block.end&&proxy_node_at(base,t,block.end,&table);t=proxy_node_next(base,&table))
   for(const unsigned char*s=table.children;s<table.end&&proxy_node_at(base,s,table.end,&string);s=proxy_node_next(base,&string)){
    if(string.type!=1||lstrcmpW(string.key,L"ProductName"))continue;
    WCHAR value[32]={0};size_t count=(size_t)(string.end-string.value)/2;if(count>string.value_length)count=string.value_length;
    if(count>=sizeof(value)/sizeof(*value))continue;
    memcpy(value,string.value,count*2);if(!lstrcmpiW(value,L"OptiScaler"))return 1;
   }
 }
 return 0;
}
/* Beside another module hooking Intel's runtime, whether a CreateContext caller is OptiScaler: only its contexts are
 * accelerated (this header's first comment); the log names any other caller's module. */
static int proxy_caller_accelerable(void*caller){
 HMODULE module=NULL;char path[MAX_PATH]={0};
 if(caller&&GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,(const char*)caller,&module))
  GetModuleFileNameA(module,path,sizeof(path));  /* (Wine resolves a NULL address to the program) */
 if(module&&module!=proxy_module&&module!=original_module&&proxy_module_is_optiscaler(module))return 1;
 const char*leaf=strrchr(path,'\\');char line[MAX_PATH+400];
 snprintf(line,sizeof(line),"FAST_SKIP beside another module hooking Intel's XeFG runtime only OptiScaler's own contexts are accelerated; "
          "this one (created from %s) keeps the caller's device and runs Intel's or that module's shaders\n",leaf?leaf+1:*path?path:"code outside any module");
 proxy_log(line);return 0;
}

/* ------------------------------------------------------------------------------------------- stepping aside */

static volatile LONG proxy_owner_foreign,proxy_aside;
static struct scoped_tables*proxy_owner_tables;
static struct{ID3D12PipelineState*ours,*intel;} proxy_pairs[256];static UINT proxy_pair_count;static SRWLOCK proxy_pair_lock=SRWLOCK_INIT;
static int proxy_aside_active(void){return InterlockedCompareExchange(&proxy_aside,0,0)!=0;}
static ID3D12PipelineState*proxy_intel_pipeline(ID3D12PipelineState*p){
 ID3D12PipelineState*intel=NULL;AcquireSRWLockShared(&proxy_pair_lock);
 for(UINT i=0;i<proxy_pair_count;i++)if(proxy_pairs[i].ours==p){intel=proxy_pairs[i].intel;break;}
 ReleaseSRWLockShared(&proxy_pair_lock);return intel;
}
/* Once stepped aside. SetPipelineState binds a replaced pipeline as Intel's original. Dispatch rebinds Intel's original
 * when a list still has a replaced pipeline bound from before (another thread recording when the context stepped
 * aside), so no replacement runs without its own dispatch size; the lists' bindings are tracked in bindings[] (lists
 * not tracked before never bound a replacement). */
static void proxy_aside_bind(ID3D12GraphicsCommandList*l,ID3D12PipelineState*p){
 AcquireSRWLockExclusive(&fast_record_lock);for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)bindings[b].p=p;ReleaseSRWLockExclusive(&fast_record_lock);
}
static void STDMETHODCALLTYPE proxy_aside_set(ID3D12GraphicsCommandList*l,ID3D12PipelineState*p){
 ID3D12PipelineState*intel=p?proxy_intel_pipeline(p):NULL;set_original(l,intel?intel:p);proxy_aside_bind(l,intel?intel:p);
}
static void STDMETHODCALLTYPE proxy_aside_dispatch_hook(ID3D12GraphicsCommandList*l,UINT x,UINT y,UINT z){
 ID3D12PipelineState*bound=NULL;AcquireSRWLockShared(&fast_record_lock);for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)bound=bindings[b].p;ReleaseSRWLockShared(&fast_record_lock);
 ID3D12PipelineState*intel=bound?proxy_intel_pipeline(bound):NULL;
 if(intel){set_original(l,intel);proxy_aside_bind(l,intel);}
 dispatch_original(l,x,y,z);
}
/* The owner context steps aside (once). Its private tables return to plain forwarding, as when it is released, except
 * that SetPipelineState maps each replaced pipeline to Intel's original; this project's resources stay alive (work
 * recorded earlier may still use them) until the context is destroyed. */
static void proxy_aside_now(const char*why){
 if(!proxy_owner_foreign||InterlockedExchange(&proxy_aside,1))return;
 struct scoped_tables*t=proxy_owner_tables;
 /* slot by slot, atomically: other threads keep calling through these tables */
 if(t){for(UINT i=0;i<SCOPED_device_COUNT;i++)InterlockedExchangePointer(&t->device[i],scoped_device_vtable[i]);
  for(UINT i=0;i<SCOPED_queue_COUNT;i++)InterlockedExchangePointer(&t->queue[i],scoped_queue_vtable[i]);
  for(UINT i=0;i<SCOPED_list_COUNT;i++)InterlockedExchangePointer(&t->list[i],i==SCOPED_list_SetPipelineState?(void*)proxy_aside_set:
   i==SCOPED_list_Dispatch?(void*)proxy_aside_dispatch_hook:scoped_list_vtable[i]);}
 char line[300];snprintf(line,sizeof(line),"FAST_ASIDE %s, with another module hooking Intel's XeFG runtime: this context now runs Intel's (or that module's) shaders; FreeFG's are off until it is destroyed\n",why);
 proxy_log(line);logline(line);
}
/* model_owner.h: a census or work-order check that failed. With another module hooking Intel's runtime the owner context
 * steps aside (1, the caller returns without failing); otherwise the check stays fatal (0). */
static int proxy_census_soft(const char*why){if(!proxy_owner_foreign)return 0;proxy_aside_now(why);return 1;}
/* dispatch_hook: a network dispatch before the deferred initialisation has built the network (initialisation tail-called
 * and no call on its handle has run the deferred work yet) steps aside instead of failing. */
static int proxy_dispatch_unready(uint64_t shader){
 if(!proxy_owner_foreign||graph_ready||!graph_enabled||proxy_aside_active())return 0;
 if(shader!=0xfec421a3b6a0632bULL&&shader!=0x558c3931ba6fb064ULL&&shader!=0x08155f47bc92811bULL&&shader!=0x18a0d2663b5d5282ULL
    &&shader!=0x3c5180037dafdbb8ULL&&shader!=0x8b17a4f9fcb35e18ULL&&shader!=0x990b9bf8cf279d27ULL&&shader!=0x4470217240e7372aULL)return 0;
 proxy_aside_now("network work arrived before the deferred initialisation");return 1;
}
/* dispatch_hook, holding fast_record_lock, once stepped aside: this dispatch as Intel recorded it (its pipeline as
 * Intel's original, its group counts unscaled). */
static void proxy_aside_dispatch(ID3D12GraphicsCommandList*l,UINT x,UINT y,UINT z){
 UINT at=nbinding;for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)at=b;
 ID3D12PipelineState*intel=at<nbinding?proxy_intel_pipeline(bindings[at].p):NULL;
 if(intel){set_original(l,intel);bindings[at].p=intel;}
 dispatch_original(l,x,y,z);
}
/* fast_compute, foreign owner only: a pipeline built from a replacement gets Intel's original beside it. */
static void proxy_pair_note(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,ID3D12PipelineState*ours){
 if(!proxy_owner_foreign||!ours||proxy_aside_active())return;
 if(!profile_lists_replacement(hash(desc->CS.pShaderBytecode,desc->CS.BytecodeLength))||proxy_intel_pipeline(ours))return;
 ID3D12PipelineState*intel=NULL;
 if(FAILED(compute_original(d,desc,&IID_ID3D12PipelineState,(void**)&intel))||!intel){proxy_aside_now("Intel's original pipeline could not be created beside a replacement");return;}
 AcquireSRWLockExclusive(&proxy_pair_lock);int stored=proxy_pair_count<sizeof(proxy_pairs)/sizeof(*proxy_pairs);
 if(stored){proxy_pairs[proxy_pair_count].ours=ours;proxy_pairs[proxy_pair_count++].intel=intel;}
 ReleaseSRWLockExclusive(&proxy_pair_lock);
 if(!stored){ID3D12PipelineState_Release(intel);proxy_aside_now("more replaced pipelines than this build pairs");}
}
/* fast_finish, after the owner's resources were released: Intel's paired pipelines go too, and the next owner starts
 * fresh. */
static void proxy_owner_released(void){
 AcquireSRWLockExclusive(&proxy_pair_lock);
 for(UINT i=0;i<proxy_pair_count;i++)ID3D12PipelineState_Release(proxy_pairs[i].intel);
 memset(proxy_pairs,0,sizeof(proxy_pairs));proxy_pair_count=0;ReleaseSRWLockExclusive(&proxy_pair_lock);
 proxy_owner_tables=NULL;InterlockedExchange(&proxy_owner_foreign,0);InterlockedExchange(&proxy_aside,0);
}

/* ------------------------------------------------------------------------------------------- deferred work */

static SRWLOCK proxy_lock=SRWLOCK_INIT;
static volatile LONG proxy_deferred;  /* entries in the three tables below; the per-frame path reads only this */
static struct{xefg_swapchain_handle_t*out;ID3D12Device*device;} proxy_creates[4];
static struct{xefg_swapchain_handle_t handle;ID3D12CommandQueue*queue;int owner;} proxy_ready[16];
static struct{xefg_swapchain_handle_t handle;int settings_owned;} proxy_finishes[16];
/* A scoped device that no context claimed (creation failed, or the caller lost the handle): released like the ordinary
 * path's failed creation (Intel may still hold a reference; the object lives until it drops it). */
static void proxy_release_device(ID3D12Device*scoped){scoped_remember((void*)scoped,scoped);scoped_destroy((void*)scoped);}
/* A caller's handle output read without trusting the pointer (its storage may be gone by now). */
static xefg_swapchain_handle_t proxy_read_handle(xefg_swapchain_handle_t*out){
 xefg_swapchain_handle_t value=NULL;SIZE_T n=0;
 return ReadProcessMemory(GetCurrentProcess(),out,&value,sizeof(value),&n)&&n==sizeof(value)?value:NULL;
}
/* Pending releases after Destroy calls that tail-called Intel (ordinary path: fast_finish and scoped_destroy after a
 * successful destruction). Run at the next CreateContext and initialisation, never for a handle still in use. */
static void proxy_finish_deferred(xefg_swapchain_handle_t keep){
 if(!InterlockedCompareExchange(&proxy_deferred,0,0))return;
 for(;;){
  xefg_swapchain_handle_t handle=NULL;int settings_owned=0;AcquireSRWLockExclusive(&proxy_lock);
  for(UINT i=0;i<16&&!handle;i++)if(proxy_finishes[i].handle&&proxy_finishes[i].handle!=keep){handle=proxy_finishes[i].handle;settings_owned=proxy_finishes[i].settings_owned;memset(&proxy_finishes[i],0,sizeof(proxy_finishes[i]));InterlockedDecrement(&proxy_deferred);}
  ReleaseSRWLockExclusive(&proxy_lock);if(!handle)return;
  AcquireSRWLockExclusive(&fast_lifecycle_lock);fast_finish(handle);scoped_destroy(handle);ReleaseSRWLockExclusive(&fast_lifecycle_lock);
  if(settings_owned)mfg_settings_clear_context();
 }
}
/* A call on a handle whose release is pending means its Destroy did not destroy it: the release is dropped. */
static void proxy_handle_alive(xefg_swapchain_handle_t handle){
 if(!handle||!InterlockedCompareExchange(&proxy_deferred,0,0))return;
 AcquireSRWLockExclusive(&proxy_lock);int dropped=0;
 for(UINT i=0;i<16;i++)if(proxy_finishes[i].handle==handle){memset(&proxy_finishes[i],0,sizeof(proxy_finishes[i]));InterlockedDecrement(&proxy_deferred);dropped=1;}
 ReleaseSRWLockExclusive(&proxy_lock);
 if(dropped)proxy_log("FAST_COEXIST a destroyed context is still in use; its resources stay\n");
}

/* CreateContext with another module hooking Intel's runtime: the scoped device (if this context is OptiScaler's and a
 * candidate) is remembered with the caller's output pointer, then the wrapper tail-calls Intel with it. A creation
 * that reuses an output pointer replaces that pointer's unclaimed entry (its caller has overwritten the handle it got,
 * which was never initialised or destroyed through this proxy). With all four entries awaiting their initialisation,
 * the context is not scoped: an entry is never evicted, since its context may still be initialised. */
static ID3D12Device*proxy_create_foreign(ID3D12Device*device,xefg_swapchain_handle_t*out,void*caller){
 proxy_finish_deferred(NULL);
 if(!device||!out||!proxy_caller_accelerable(caller))return NULL;
 AcquireSRWLockExclusive(&fast_lifecycle_lock);ID3D12Device*scoped=fast_candidate(device,caller)?scoped_begin(device):NULL;ReleaseSRWLockExclusive(&fast_lifecycle_lock);
 if(!scoped)return NULL;
 ID3D12Device*stale=NULL;AcquireSRWLockExclusive(&proxy_lock);int slot=-1;
 for(int i=0;i<4&&slot<0;i++)if(proxy_creates[i].device&&proxy_creates[i].out==out)slot=i;
 for(int i=0;i<4&&slot<0;i++)if(!proxy_creates[i].device)slot=i;
 if(slot>=0){
  if(proxy_creates[slot].device)stale=proxy_creates[slot].device;else InterlockedIncrement(&proxy_deferred);
  proxy_creates[slot].out=out;proxy_creates[slot].device=scoped;
 }
 ReleaseSRWLockExclusive(&proxy_lock);
 if(stale)proxy_release_device(stale);
 if(slot<0){proxy_release_device(scoped);proxy_log("FAST_COEXIST 4 contexts await their first initialisation; this one keeps the caller's device\n");return NULL;}
 return scoped;
}
/* COM identity (IUnknown) of an object; NULL if it has none. */
static IUnknown*proxy_identity(IUnknown*object){
 IUnknown*identity=NULL;if(!object||FAILED(IUnknown_QueryInterface(object,&IID_IUnknown,(void**)&identity)))return NULL;
 IUnknown_Release(identity);return identity;  /* compared only, while the caller holds the object */
}
/* The handle's scoped device, from the creation awaiting its claim: the entry whose output pointer now holds the handle,
 * or else (at initialisation, queue given) the only entry whose device is the queue's device. Called at the handle's
 * initialisation and destruction. With entries left but none matched, the handle stays unscoped (its context was not
 * scoped, or its caller moved the handle and created more than one context on that device) and the log says so. */
static void proxy_claim(xefg_swapchain_handle_t handle,ID3D12CommandQueue*queue){
 if(!handle||!InterlockedCompareExchange(&proxy_deferred,0,0))return;
 int known=fast_context_scope(handle)!=0;IUnknown*queue_device=NULL;
 if(queue&&!known){ID3D12Device*d=NULL;if(SUCCEEDED(ID3D12CommandQueue_GetDevice(queue,&IID_ID3D12Device,(void**)&d))&&d){queue_device=proxy_identity((IUnknown*)d);ID3D12Device_Release(d);}}
 ID3D12Device*claimed=NULL;int by_device=-1,matches=0,via_device=0;
 AcquireSRWLockExclusive(&proxy_lock);
 for(int i=0;i<4;i++)if(proxy_creates[i].device){
  if(!claimed&&proxy_read_handle(proxy_creates[i].out)==handle){claimed=proxy_creates[i].device;memset(&proxy_creates[i],0,sizeof(proxy_creates[i]));InterlockedDecrement(&proxy_deferred);}
  else if(queue_device&&proxy_identity(((struct scoped_com*)proxy_creates[i].device)->real)==queue_device){matches++;by_device=i;}}
 if(!claimed&&!known&&matches==1){claimed=proxy_creates[by_device].device;memset(&proxy_creates[by_device],0,sizeof(proxy_creates[by_device]));InterlockedDecrement(&proxy_deferred);via_device=1;}
 ReleaseSRWLockExclusive(&proxy_lock);
 if(claimed&&known){proxy_release_device(claimed);return;}  /* an older creation whose output now holds a scoped context */
 if(claimed){scoped_remember(handle,claimed);
  if(!fast_context_scope(handle)){proxy_release_device(claimed);return;}  /* the context table is full (logged) */
  if(via_device)proxy_log("FAST_COEXIST a context's creation was matched by its device (its output pointer no longer holds the handle)\n");
 }else if(!known&&matches>1)
  proxy_log("FAST_COEXIST a context on the device of several pending creations matched none of them; it is initialised with the caller's queue\n");
}
/* Initialisation with another module hooking Intel's runtime: claim, prepare the owner as the ordinary path does, and
 * leave the scoped queue's reference and the context's readiness to the next call on its handle. */
static ID3D12CommandQueue*proxy_init_foreign(xefg_swapchain_handle_t handle,ID3D12CommandQueue*queue){
 proxy_finish_deferred(handle);proxy_handle_alive(handle);proxy_claim(handle,queue);
 UINT before=fast_scope;fast_begin_init(handle);
 int owner=fast_scope&&fast_context_scope(handle)==fast_scope;
 if(owner&&!before&&fast_scope){
  struct scoped_com*d=NULL;AcquireSRWLockShared(&scoped_lock);for(UINT i=0;i<16;i++)if(scoped_contexts[i].handle==handle)d=scoped_contexts[i].device;ReleaseSRWLockShared(&scoped_lock);
  proxy_owner_tables=d?d->tables:NULL;InterlockedExchange(&proxy_owner_foreign,1);
  proxy_log("FAST_COEXIST this context is accelerated beside the other module; replaced pipelines keep Intel's originals beside them\n");
 }
 ID3D12CommandQueue*scoped=scoped_application_queue(handle,queue);
 if(owner||scoped){
  ID3D12CommandQueue*old=NULL;AcquireSRWLockExclusive(&proxy_lock);int slot=-1;
  for(int i=0;i<16;i++)if(proxy_ready[i].handle==handle){slot=i;old=proxy_ready[i].queue;break;}
  for(int i=0;i<16&&slot<0;i++)if(!proxy_ready[i].handle){slot=i;InterlockedIncrement(&proxy_deferred);}
  if(slot>=0){proxy_ready[slot].handle=handle;proxy_ready[slot].queue=scoped;proxy_ready[slot].owner=owner;}
  ReleaseSRWLockExclusive(&proxy_lock);
  if(old)scoped_release((void*)old);
  if(slot<0)proxy_log("FAST_COEXIST 16 contexts await their deferred initialisation work; this one keeps its queue reference\n");
 }
 return scoped;
}
static void proxy_frames_learn(xefg_swapchain_handle_t handle,UINT frames);
/* The handle's deferred initialisation work, at the first call that carries the handle after its initialisation tail-
 * called (proxy_ready_first), before that call reaches Intel: the ordinary path's after-initialisation work. Its result
 * check is Intel's own answer to xefgSwapChainD3D12GetInitializationParameters, which succeeds only for an initialised
 * context (a caller may still use a handle whose initialisation failed); that answer also gives the frame count a
 * maximum-count initialisation chose. */
static void proxy_ready_now(xefg_swapchain_handle_t handle){
 ID3D12CommandQueue*queue=NULL;int found=0;AcquireSRWLockExclusive(&proxy_lock);
 for(UINT i=0;i<16;i++)if(proxy_ready[i].handle==handle){queue=proxy_ready[i].queue;memset(&proxy_ready[i],0,sizeof(proxy_ready[i]));InterlockedDecrement(&proxy_deferred);found=1;break;}
 ReleaseSRWLockExclusive(&proxy_lock);if(!found)return;
 if(queue)scoped_release((void*)queue);
 static __typeof__(&xefgSwapChainD3D12GetInitializationParameters) initialized;
 if(!initialized)initialized=(void*)resolve("xefgSwapChainD3D12GetInitializationParameters");
 xefg_swapchain_d3d12_init_params_t params={0};
 if(initialized&&initialized(handle,&params)!=XEFG_SWAPCHAIN_RESULT_SUCCESS){
  proxy_log("FAST_COEXIST a context's initialisation did not succeed (Intel reports no initialisation parameters); nothing is prepared for it\n");return;}
 if(initialized)proxy_frames_learn(handle,params.maxInterpolatedFrames);
 fast_ready(handle);mfg_tag_capture(handle);
 if(fast_scope&&fast_context_scope(handle)==fast_scope)mfg_settings_note_context(handle);
}
/* Before a call that carries a handle and comes after its initialisation (D3D12GetSwapChainPtr, SetNumInterpolatedFrames,
 * GetLastPresentStatus, TagFrameConstants): a pending release is dropped (the handle is in use) and the deferred
 * initialisation work runs, so the model census holds what the initialisation allocated and nothing that a frame-count
 * change allocates later. */
static void proxy_ready_first(xefg_swapchain_handle_t handle){
 if(!handle||!InterlockedCompareExchange(&proxy_deferred,0,0))return;
 proxy_handle_alive(handle);proxy_ready_now(handle);
}
/* Destroy, either path: a context destroyed before its deferred initialisation work ran drops that work. */
static void proxy_ready_drop(xefg_swapchain_handle_t handle){
 if(!handle||!InterlockedCompareExchange(&proxy_deferred,0,0))return;
 ID3D12CommandQueue*queue=NULL;AcquireSRWLockExclusive(&proxy_lock);
 for(UINT i=0;i<16;i++)if(proxy_ready[i].handle==handle){queue=proxy_ready[i].queue;memset(&proxy_ready[i],0,sizeof(proxy_ready[i]));InterlockedDecrement(&proxy_deferred);break;}
 ReleaseSRWLockExclusive(&proxy_lock);if(queue)scoped_release((void*)queue);
}
/* Destroy with another module hooking Intel's runtime: the ordinary path's work before the call, and the release
 * after a successful destruction queued for the next CreateContext or initialisation. */
static void proxy_destroy_foreign(xefg_swapchain_handle_t handle){
 if(!handle)return;
 proxy_claim(handle,NULL);  /* a context destroyed before its initialisation: its scoped device is released as below */
 proxy_ready_drop(handle);
 int settings_owned=fast_scope&&fast_context_scope(handle)==fast_scope;fast_report(handle);
 if(!fast_context_scope(handle))return;
 AcquireSRWLockExclusive(&proxy_lock);int slot=-1;
 for(int i=0;i<16&&slot<0;i++)if(!proxy_finishes[i].handle)slot=i;
 if(slot>=0){proxy_finishes[slot].handle=handle;proxy_finishes[slot].settings_owned=settings_owned;InterlockedIncrement(&proxy_deferred);}
 ReleaseSRWLockExclusive(&proxy_lock);
 if(slot<0)proxy_log("FAST_RETAIN 16 releases pending; this context's resources are held until process exit\n");
}

/* ------------------------------------------------------------------------------- frame count and frame status */

/* Each context's current number of generated frames per real frame, from its initialisation and every successful
 * xefgSwapChainSetNumInterpolatedFrames (0: not known yet). */
static struct{xefg_swapchain_handle_t handle;UINT frames;} proxy_frames[16];static SRWLOCK proxy_frames_lock=SRWLOCK_INIT;
static UINT proxy_frames_note(xefg_swapchain_handle_t handle,UINT frames){
 if(!handle)return frames;  /* free slots hold NULL handles */
 UINT previous=0;AcquireSRWLockExclusive(&proxy_frames_lock);int slot=-1;
 for(int i=0;i<16;i++)if(proxy_frames[i].handle==handle){slot=i;previous=proxy_frames[i].frames;break;}
 for(int i=0;i<16&&slot<0;i++)if(!proxy_frames[i].handle)slot=i;
 if(slot>=0){proxy_frames[slot].handle=handle;proxy_frames[slot].frames=frames;}
 ReleaseSRWLockExclusive(&proxy_frames_lock);return previous;
}
static void proxy_frames_forget(xefg_swapchain_handle_t handle){
 if(!handle)return;
 AcquireSRWLockExclusive(&proxy_frames_lock);for(int i=0;i<16;i++)if(proxy_frames[i].handle==handle)memset(&proxy_frames[i],0,sizeof(proxy_frames[i]));ReleaseSRWLockExclusive(&proxy_frames_lock);
}
/* Intel's header: "By default, XeSS-FG swap chain will produce the maximum number of interpolated frames specified
 * during initialization", so the count after initialisation is that maximum, and the first
 * xefgSwapChainSetNumInterpolatedFrames to another count is a change (the runtime rebuilds for it). */
static void proxy_frames_init(xefg_swapchain_handle_t handle,const xefg_swapchain_d3d12_init_params_t*params){
 if(!handle)return;  /* the SDK rejects the call */
 UINT frames=params&&params->maxInterpolatedFrames!=XEFG_SWAPCHAIN_USE_MAX_SUPPORTED_INTERPOLATED_FRAMES?params->maxInterpolatedFrames:0;
 proxy_frames_note(handle,frames);
 char line[160];if(frames)snprintf(line,sizeof(line),"MFG_FACTOR context initialised for up to %ux\n",frames+1);
 else snprintf(line,sizeof(line),"MFG_FACTOR context initialised for the runtime's maximum frame count\n");proxy_log(line);
}
/* The count a maximum-count initialisation chose (proxy_ready_now), for a context whose count is not known yet. */
static void proxy_frames_learn(xefg_swapchain_handle_t handle,UINT frames){
 if(!handle||!frames||frames==XEFG_SWAPCHAIN_USE_MAX_SUPPORTED_INTERPOLATED_FRAMES)return;
 int learned=0;AcquireSRWLockExclusive(&proxy_frames_lock);
 for(int i=0;i<16;i++)if(proxy_frames[i].handle==handle&&!proxy_frames[i].frames){proxy_frames[i].frames=frames;learned=1;}
 ReleaseSRWLockExclusive(&proxy_frames_lock);
 if(learned){char line[120];snprintf(line,sizeof(line),"MFG_FACTOR the runtime's maximum for this context is %ux\n",frames+1);proxy_log(line);}
}
/* After a successful xefgSwapChainSetNumInterpolatedFrames that changed the owner context's count: Intel's runtime has
 * rebuilt its pipelines and resources for the new count, so the views and the SDK-released lists and heaps this
 * project tracked for the old count are retired once the GPU has finished with them (the XeSSMFG build did this from
 * the enabler's ApplyMultiplier). Lock order lifecycle -> record -> frame, as xefgSwapChainDestroy's teardown. */
static void proxy_frames_changed(xefg_swapchain_handle_t handle,UINT frames){
 UINT previous=proxy_frames_note(handle,frames);
 if(previous==frames)return;
 char line[200];snprintf(line,sizeof(line),"MFG_FACTOR %ux (%u generated frames per real frame)\n",frames+1,frames);proxy_log(line);
 if(!previous)return;  /* the first count after a maximum-count initialisation: nothing was built for another count */
 AcquireSRWLockExclusive(&fast_lifecycle_lock);
 if(!fast_scope||fast_context_scope(handle)!=fast_scope||proxy_aside_active()){ReleaseSRWLockExclusive(&fast_lifecycle_lock);return;}
 AcquireSRWLockExclusive(&fast_record_lock);
 if(frame_output_count&&graph_queue){
  ID3D12Fence*fence=NULL;HANDLE event=CreateEventA(NULL,FALSE,FALSE,NULL);int idle=0;
  if(event&&SUCCEEDED(ID3D12Device_CreateFence(model_device,0,0,&IID_ID3D12Fence,(void**)&fence))&&SUCCEEDED(ID3D12CommandQueue_Signal(graph_queue,fence,1))&&SUCCEEDED(ID3D12Fence_SetEventOnCompletion(fence,1,event)))idle=WaitForSingleObject(event,10000)==WAIT_OBJECT_0;
  if(fence)ID3D12Fence_Release(fence);if(event)CloseHandle(event);
  if(!idle)proxy_log("MFG_FACTOR GPU completion unconfirmed; old output views kept\n");
  else if(mfg_second_phase_pending)proxy_log("MFG_FACTOR changed between generated frames; old output views kept\n");
  else{AcquireSRWLockExclusive(&frame_lock);frame_release_output_views();ReleaseSRWLockExclusive(&frame_lock);proxy_log("MFG_FACTOR old output views retired after GPU completion\n");}
 }
 scoped_collect_idle(fast_scope);
 snprintf(line,sizeof(line),"MFG_RETIRED heaps=%llu lists=%llu queues=%llu live_heaps=%u frame_descriptors=%u\n",(unsigned long long)mfg_retired_heaps,(unsigned long long)mfg_retired_lists,(unsigned long long)mfg_retired_queues,mfg_live_heap_count,frame_desc_count);proxy_log(line);
 ReleaseSRWLockExclusive(&fast_record_lock);ReleaseSRWLockExclusive(&fast_lifecycle_lock);
}
/* Generated frames reported by Intel's SDK (framesPresented - 1 per present), for the pacing layer's signal
 * (mfg_pace_signal.h): it moves whenever XeFG generates, whoever's shaders run (this project's, Intel's, or another
 * module's at any frame count). From the caller's own xefgSwapChainGetLastPresentStatus calls; a caller that makes
 * none (OptiScaler builds without its low-latency inputs) gets one status read per tagged frame instead
 * (BC250_XEFG_STATUS_POLL=0 turns that off). */
static volatile LONG proxy_status_caller_tick,proxy_status_caller_seen;
static void proxy_status_count(const xefg_swapchain_present_status_t*status){
 if(!status||status->framesPresented<2)return;
 if(!InterlockedExchangeAdd64(&proxy_status_generated,(LONG64)status->framesPresented-1)){char line[120];
  snprintf(line,sizeof(line),"MFG_STATUS XeFG generates: %u frames per present (SDK status)\n",status->framesPresented);proxy_log(line);}
}
static void proxy_status_from_caller(const xefg_swapchain_present_status_t*status){
 InterlockedExchange(&proxy_status_caller_tick,(LONG)GetTickCount());InterlockedExchange(&proxy_status_caller_seen,1);proxy_status_count(status);
}
static __typeof__(&xefgSwapChainGetLastPresentStatus) proxy_status_get;
static void proxy_status_poll(xefg_swapchain_handle_t handle){
 if(!handle)return;  /* the SDK rejects the call; nothing to read */
 static int enabled=-1;if(enabled<0)enabled=env_uint("BC250_XEFG_STATUS_POLL",1)!=0;
 if(!enabled||(InterlockedCompareExchange(&proxy_status_caller_seen,0,0)&&(DWORD)GetTickCount()-(DWORD)proxy_status_caller_tick<1000))return;
 if(!proxy_status_get&&!(proxy_status_get=(void*)resolve("xefgSwapChainGetLastPresentStatus")))return;
 xefg_swapchain_present_status_t status={0};if(proxy_status_get(handle,&status)==XEFG_SWAPCHAIN_RESULT_SUCCESS)proxy_status_count(&status);
}
/* xefgSwapChainTagFrameConstants, before the call (it then tail-calls): the handle's deferred initialisation work, and
 * the status read. */
static void proxy_frame_tick(xefg_swapchain_handle_t handle){
 proxy_ready_first(handle);proxy_status_poll(handle);
}
