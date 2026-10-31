/* SPDX-License-Identifier: MIT
 * Enabler-free entry point of the BC250 add-on (release/INTEL-FREE.md, variant intel-free-2x). This libxess_fg.dll sits
 * where the game or OptiScaler loads Intel's XeFG runtime and exports Intel's 57 entries with their ordinals: five are
 * wrapped here with the add-on's scoped acceleration (generated mfg_proxy_exports.h), the others are export forwarders
 * (proxy.def). Intel's unmodified runtime is loaded from bc250_xefg_original.dll beside this file by its absolute path
 * after a size and FNV-1a check (original_manifest.h). No Intel code is patched: every call reaches the runtime through
 * its own export table, and the SDK sees only the scoped D3D12 objects it is given.
 *
 * Two builds come from this file. intel-free-2x (release/intel_free_2x.json): without the XeSSMFG enabler, XeFG
 * generates one frame per real frame on this GPU, the limit Intel's runtime applies to GPUs other than its own. So that
 * build has no multiplier hook, no frame-start pacer (it acts at 3x/4x only) and no pooled model sets, and keeps the
 * one-frame model checks (no XEFG_MFG_RESEARCH): the SDK initialises its 27-buffer native set only. A context that would
 * generate more than one frame per real frame keeps Intel's shaders.
 *
 * intel-free-mfg (release/intel_free_mfg.json, XEFG_PROXY_MFG): the same at any frame count Intel's runtime runs. It
 * keeps the multi-frame network support of the enabler-era Intel-free build (model census of the 2x, multi-frame or both
 * model sets, mfg-finish kernels, pooled model sets and pipelines, retirement), takes the frame count from
 * xefgSwapChainSetNumInterpolatedFrames, and counts the frames the SDK reports presented for the pacing layer. It
 * changes no limit itself: beyond one generated frame per real frame it accelerates only beside another module the
 * user installed that hooks Intel's runtime (to lift Intel's limit), and only OptiScaler's own contexts there; it then
 * keeps that module's view of its callers and steps aside rather than end the game (mfg_proxy_coexist.h). Without such
 * a module it accelerates what the 2x build accelerates. This proxy has no frame-start pacer. MFG Unlocker's output
 * pacing does not pace game simulation starts; the OptiScaler fork supplies the adaptive correction through XeLL.
 */
#define WIDL_C_INLINE_WRAPPERS
#define COBJMACROS
#define INITGUID
#define XEFG_SWAPCHAIN_EXPORT_API
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <stdio.h>
#include <stdint.h>
#include <xefg_swapchain_d3d12.h>
#include <xefg_swapchain_debug.h>
#include "original_manifest.h"
int _fltused;
static HMODULE proxy_module,original_module;
static wchar_t proxy_directory[32768];
static HANDLE logfile=INVALID_HANDLE_VALUE;
static SRWLOCK log_lock=SRWLOCK_INIT;
static void proxy_log(const char*s){if(logfile!=INVALID_HANDLE_VALUE){AcquireSRWLockExclusive(&log_lock);DWORD n;WriteFile(logfile,s,(DWORD)strlen(s),&n,NULL);ReleaseSRWLockExclusive(&log_lock);}}
#include "mfg_settings.h"
#include "scoped_com.h"
#include "fast_trial.h"
#include "mfg_scoped_retire.h"
static volatile LONG64 proxy_status_generated;  /* mfg_proxy_coexist.h; the pacing signal adds it */
static volatile LONG proxy_status_multiplier; /* actual frames per present, for the layer's MFG jitter allowance */
static void proxy_snapshot_entries(const wchar_t*path);
#include "mfg_pace_signal.h"
static int original_verified(const wchar_t*path){
 HANDLE f=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);if(f==INVALID_HANDLE_VALUE)return 0;
 LARGE_INTEGER size;int ok=GetFileSizeEx(f,&size)&&size.QuadPart==ORIGINAL_BYTES;
 unsigned char bytes[1024];DWORD count;UINT64 total=0;uint64_t h=0xcbf29ce484222325ULL;
 while(ok&&total<ORIGINAL_BYTES){if(!ReadFile(f,bytes,sizeof(bytes),&count,NULL)||!count){ok=0;break;}total+=count;for(DWORD i=0;i<count;i++)h=h*0x100000001b3ULL^bytes[i];}
 CloseHandle(f);return ok&&total==ORIGINAL_BYTES&&h==ORIGINAL_HASH;
}
static INIT_ONCE mfg_once=INIT_ONCE_STATIC_INIT;
/* The initialisation runs once, whatever its outcome: a missing or altered runtime is logged once and every later call
 * answers CANT_LOAD_LIBRARY at once (a retry per call reopened the log and re-hashed the 22 MB runtime). */
static int mfg_ready;
static void mfg_initialize_once(void){
 /* Pinned from here on: the pacing-signal thread runs for the life of the process and Intel's runtime keeps the scoped
  * objects' tables, so an unload by the caller (FreeLibrary after frame generation is turned off) must not unmap them. */
 HMODULE self;GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,(LPCWSTR)(void*)mfg_initialize_once,&self);
 DWORD n=GetModuleFileNameW(proxy_module,proxy_directory,32768);if(!n||n>=32768)return;wchar_t*slash=wcsrchr(proxy_directory,L'\\');if(!slash)return;slash[1]=0;
 static wchar_t path[32768];if(wcslen(proxy_directory)+64>=32768)return;
 wcscpy(path,proxy_directory);wcscat(path,L"BC250-MFG.log");logfile=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
 mfg_settings_init();
 wcscpy(path,proxy_directory);wcscat(path,L"bc250_xefg_original.dll");
 if(!original_verified(path)){proxy_log("MFG proxy: bc250_xefg_original.dll is missing or is not the pinned Intel XeFG runtime (size or hash); XeFG is unavailable\n");return;}
 original_module=LoadLibraryExW(path,NULL,LOAD_WITH_ALTERED_SEARCH_PATH);
 if(!original_module){char line[120];snprintf(line,sizeof(line),"MFG proxy: Intel XeFG runtime did not load (error %lu)\n",GetLastError());proxy_log(line);return;}
 mfg_pace_signal_start();
 proxy_snapshot_entries(path);
 proxy_log("MFG proxy ready: Intel's XeFG runtime unmodified beside it, own shaders only, at the frame count the runtime runs\n");
 mfg_ready=1;
}
static BOOL CALLBACK mfg_initialize(PINIT_ONCE once,PVOID arg,PVOID*out){(void)once;(void)arg;(void)out;mfg_initialize_once();return TRUE;}
/* The Intel runtime's entry point, once this module is initialised and the runtime verified; NULL otherwise. */
static FARPROC resolve(const char*name){
 if(!InitOnceExecuteOnce(&mfg_once,mfg_initialize,NULL,NULL)||!mfg_ready)return NULL;
 FARPROC result=GetProcAddress(original_module,name);
 if(!result){proxy_log("MFG proxy: Intel runtime lacks ");proxy_log(name);proxy_log("\n");}
 return result;
}
/* The settings' sizes from a context's swap chain, through the verified runtime this proxy loaded: by name,
 * "libxess_fg.dll" can be a game's own copy of Intel's runtime, which does not know this context. */
static void mfg_settings_note_context(xefg_swapchain_handle_t context){
 static __typeof__(&xefgSwapChainD3D12GetSwapChainPtr) get;if(!get&&!(get=(void*)resolve("xefgSwapChainD3D12GetSwapChainPtr")))return;
 IDXGISwapChain3*swap=NULL;DXGI_SWAP_CHAIN_DESC1 desc;
 if(get(context,&IID_IDXGISwapChain3,(void**)&swap)==0&&swap){
  if(SUCCEEDED(IDXGISwapChain3_GetDesc1(swap,&desc)))mfg_settings_note_size(desc.Width,desc.Height);
  IDXGISwapChain3_Release(swap);
 }
}
/* 2x only: a context is accelerated only when XeFG generates one frame per real frame. Intel's runtime allows more only
 * on GPUs it supports for that (an Intel GPU with BC250_XEFG_ANY_GPU=1); such a context keeps Intel's shaders instead of
 * meeting model checks written for the one-frame network. Called on the initialising thread, before the SDK's own
 * initialisation; xefgSwapChainGetProperties reports maxSupportedInterpolations before it. A context created without
 * a scoped device (not a candidate: BC250_XEFG_DISABLE=1, another GPU, a second context) is not asked.
 * The multi-frame proxy asks the same on its ordinary path (no other module hooks Intel's runtime), where every check
 * stays fatal, so without such a module it accelerates exactly what the 2x build accelerates; beside one, its
 * initialisation takes the foreign path (mfg_proxy_coexist.h) at any frame count. */
static int mfg_proxy_one_frame(xefg_swapchain_handle_t handle,const xefg_swapchain_d3d12_init_params_t*params){
 if(!handle||!params||!fast_context_scope(handle))return 0;  /* the SDK rejects the call, or fast_begin_init would skip it */
 UINT32 frames=params->maxInterpolatedFrames;
 if(frames==XEFG_SWAPCHAIN_USE_MAX_SUPPORTED_INTERPOLATED_FRAMES){
  __typeof__(&xefgSwapChainGetProperties) get=(void*)resolve("xefgSwapChainGetProperties");xefg_swapchain_properties_t properties={0};
  if(!get||get(handle,&properties)!=XEFG_SWAPCHAIN_RESULT_SUCCESS){proxy_log("FAST_SKIP the runtime reported no frame limit for this context\n");return 0;}
  frames=properties.maxSupportedInterpolations;
 }
 if(frames==1)return 1;
 char line[300];snprintf(line,sizeof(line),"FAST_SKIP this context generates up to %u frames per real frame with no other module hooking Intel's XeFG "
                         "runtime; this build accelerates more than one only beside such a module (Intel's shaders here)\n",frames);proxy_log(line);
 return 0;
}
/* BC250_CAPTURE_TAG_FRAMES=1 (latency captures): Intel's markers on generated frames. */
static void mfg_tag_capture(xefg_swapchain_handle_t handle){
 if(!env_uint("BC250_CAPTURE_TAG_FRAMES",0))return;
 __typeof__(&xefgSwapChainEnableDebugFeature) tag=(void*)resolve("xefgSwapChainEnableDebugFeature");
 if(!tag||tag(handle,XEFG_SWAPCHAIN_DEBUG_FEATURE_TAG_INTERPOLATED_FRAMES,1,NULL)!=0)model_fail("MFG capture tagging failed");
 proxy_log("MFG_CAPTURE generated-frame markers enabled\n");
}
#include "mfg_proxy_coexist.h"
#include "mfg_proxy_exports.h"
/* The research harness and OptiScaler-plugin builds call this; here it only runs the lazy initialisation early. */
__declspec(dllexport) BOOL WINAPI BC250MFGInitialize(void){return InitOnceExecuteOnce(&mfg_once,mfg_initialize,NULL,NULL)&&mfg_ready;}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved){(void)reserved;if(reason==DLL_PROCESS_ATTACH){proxy_module=instance;DisableThreadLibraryCalls(instance);}return TRUE;}
