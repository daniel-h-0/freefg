/* SPDX-License-Identifier: MIT
 * Startup-only settings shared with the private OptiScaler menu.
 * Include after Windows/CRT declarations and proxy_log, before probe_core.
 */
#include <wchar.h>
#include <stdlib.h>
#include "mfg_settings_contract.h"
static struct bc250_fg_settings mfg_settings_applied;
static struct bc250_fg_status mfg_settings_status;
static wchar_t mfg_settings_path[32768];
static LONG mfg_settings_loaded;
static int mfg_settings_available(void){return InterlockedCompareExchange(&mfg_settings_loaded,0,0)!=0;}
static SRWLOCK mfg_settings_lock=SRWLOCK_INIT;
/* Extend these masks only alongside qualified shader implementations. */
/* The Intel-free add-on has no scaled warps: generated frames always match the output and no filter is offered (no mask
 * bit is set). Saving accepts only the native choice (BC250MFGSaveFrameSettings). The status interface still reports
 * the context's size. */
#define MFG_SETTINGS_DOWNSCALE_MASK 0u
#define MFG_SETTINGS_UPSCALE_MASK 0u
static const wchar_t*mfg_settings_keys[]={L"ResolutionMode",L"ResolutionPercent",L"ResolutionLimit",L"DownscaleFilter",L"UpscaleFilter"};
static UINT mfg_settings_read_uint(const wchar_t*key,UINT fallback) {
 wchar_t value[64],*end=NULL;
 DWORD n=GetPrivateProfileStringW(L"BC250",key,L"",value,64,mfg_settings_path);
 if(!n)return fallback;
 if(n>=63||value[0]==L'-')return fallback;
 unsigned long result=wcstoul(value,&end,10);
 if(end==value)return fallback;
 while(*end==L' '||*end==L'\t')end++;
 if(*end&&*end!=L';'&&*end!=L'#')return fallback;  /* trailing text other than a comment */
 return (UINT)result;
}
static struct bc250_fg_settings mfg_settings_read_saved(void) {
 struct bc250_fg_settings s=bc250_fg_defaults();
 wchar_t mode[64];
 if(GetPrivateProfileStringW(L"BC250",L"ResolutionMode",L"",mode,64,mfg_settings_path))
  s.resolution=mfg_settings_read_uint(mfg_settings_keys[0],s.resolution);
 else if(mfg_settings_read_uint(L"FrameCap",0)==1)s.resolution=BC250_FG_LIMIT;
 s.percent=mfg_settings_read_uint(mfg_settings_keys[1],s.percent);
 s.height_limit=mfg_settings_read_uint(mfg_settings_keys[2],s.height_limit);
 s.downscale=mfg_settings_read_uint(mfg_settings_keys[3],s.downscale);
 s.upscale=mfg_settings_read_uint(mfg_settings_keys[4],s.upscale);
 /* An invalid value falls back alone; the other keys keep what the user chose. */
 struct bc250_fg_settings d=bc250_fg_defaults(),probe;UINT bad=0;
#define MFG_SETTINGS_KEY(field) probe=d;probe.field=s.field;if(!bc250_fg_settings_valid(&probe)){s.field=d.field;bad=1;}
 MFG_SETTINGS_KEY(resolution) MFG_SETTINGS_KEY(percent) MFG_SETTINGS_KEY(height_limit) MFG_SETTINGS_KEY(downscale) MFG_SETTINGS_KEY(upscale)
#undef MFG_SETTINGS_KEY
 if(bad)proxy_log("MFG_SETTINGS invalid INI value; that key uses its default\n");
 if(!(MFG_SETTINGS_DOWNSCALE_MASK&(1u<<s.downscale)))s.downscale=BC250_FG_BILINEAR;
 if(!(MFG_SETTINGS_UPSCALE_MASK&(1u<<s.upscale)))s.upscale=BC250_FG_BILINEAR;
 s.resolution=BC250_FG_OUTPUT;  /* a saved Scale/Limit choice of another build does not apply here */
 return s;
}
static void mfg_settings_init(void) {
 DWORD n=GetModuleFileNameW(NULL,mfg_settings_path,32768);
 if(!n||n>=32700){mfg_settings_path[0]=0;return;}
 wchar_t*slash=wcsrchr(mfg_settings_path,L'\\');if(!slash){mfg_settings_path[0]=0;return;}
 wcscpy(slash+1,L"BC250-XeFG\\settings.ini");
 mfg_settings_applied=mfg_settings_read_saved();
 mfg_settings_status.size=sizeof(mfg_settings_status);
 mfg_settings_status.version=BC250_FG_SETTINGS_VERSION;
 mfg_settings_status.applied=mfg_settings_applied;
 mfg_settings_status.downscale_mask=MFG_SETTINGS_DOWNSCALE_MASK;
 mfg_settings_status.upscale_mask=MFG_SETTINGS_UPSCALE_MASK;
 InterlockedExchange(&mfg_settings_loaded,1);
 char line[192];snprintf(line,sizeof(line),"MFG_SETTINGS mode=%u percent=%u limit=%u down=%u up=%u override=%u\n",mfg_settings_applied.resolution,mfg_settings_applied.percent,mfg_settings_applied.height_limit,mfg_settings_applied.downscale,mfg_settings_applied.upscale,mfg_settings_status.launch_override);proxy_log(line);
 proxy_log("MFG_SETTINGS Intel-free build: no scaling; generated frames match the output\n");
}
static UINT mfg_settings_cap_requested(void) {
 return 0;
}
static void mfg_settings_note_size(UINT w,UINT h) {
 UINT tw,th;if(!mfg_settings_available()||!bc250_fg_dimensions(&mfg_settings_applied,w,h,&tw,&th))return;
 AcquireSRWLockExclusive(&mfg_settings_lock);
 mfg_settings_status.output_width=w;mfg_settings_status.output_height=h;
 mfg_settings_status.generated_width=tw;mfg_settings_status.generated_height=th;mfg_settings_status.ready=1;
 ReleaseSRWLockExclusive(&mfg_settings_lock);
}
__declspec(dllexport) BOOL WINAPI BC250MFGGetFrameSettings(struct bc250_fg_status*out) {
 if(!out||out->size!=sizeof(*out)||out->version!=BC250_FG_SETTINGS_VERSION||!mfg_settings_available())return FALSE;
 AcquireSRWLockShared(&mfg_settings_lock);*out=mfg_settings_status;ReleaseSRWLockShared(&mfg_settings_lock);return TRUE;
}
__declspec(dllexport) BOOL WINAPI BC250MFGReadFrameSettings(struct bc250_fg_settings*out) {
 if(!out||!mfg_settings_available())return FALSE;
 *out=mfg_settings_read_saved();return TRUE;
}
__declspec(dllexport) BOOL WINAPI BC250MFGSaveFrameSettings(const struct bc250_fg_settings*s) {
 /* Nothing to save: generated frames always match the output here. Accept the native choice (Match output, or Scale at
  * 100%, with the default filters) without writing, so OptiScaler's menu clears its error; refuse Scale and Limit. The
  * file keeps whatever another build saved. */
 return mfg_settings_available()&&bc250_fg_settings_valid(s)&&s->downscale==BC250_FG_BILINEAR&&s->upscale==BC250_FG_BILINEAR&&
  (s->resolution==BC250_FG_OUTPUT||(s->resolution==BC250_FG_SCALE&&s->percent==100));
}

static void mfg_settings_note_context(xefg_swapchain_handle_t context) {
 HMODULE sdk=GetModuleHandleA("libxess_fg.dll");
 __typeof__(&xefgSwapChainD3D12GetSwapChainPtr) get=sdk?(void*)GetProcAddress(sdk,"xefgSwapChainD3D12GetSwapChainPtr"):NULL;
 IDXGISwapChain3*swap=NULL;DXGI_SWAP_CHAIN_DESC1 desc;
 if(get&&get(context,&IID_IDXGISwapChain3,(void**)&swap)==0&&swap) {
  if(SUCCEEDED(IDXGISwapChain3_GetDesc1(swap,&desc)))mfg_settings_note_size(desc.Width,desc.Height);
  IDXGISwapChain3_Release(swap);
 }
}
static void mfg_settings_clear_context(void) {
 AcquireSRWLockExclusive(&mfg_settings_lock);mfg_settings_status.ready=0;
 mfg_settings_status.output_width=mfg_settings_status.output_height=0;
 mfg_settings_status.generated_width=mfg_settings_status.generated_height=0;
 ReleaseSRWLockExclusive(&mfg_settings_lock);
}
