/* SPDX-License-Identifier: MIT
 * CPU-only check of the enabler-free libxess_fg.dll proxy under Wine (release/check_proxy_wine.py): Windows' loader resolves
 * its export forwarders to bc250_xefg_original.dll, its wrapped entry reaches Intel's runtime only after the size and hash
 * check, and its settings exports answer. No D3D12 device is created and no GPU work is submitted.
 * PROXY_CHECK_FORWARDERS=1 also calls a forwarded entry (xefgSwapChainGetVersion) first.
 */
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <xefg_swapchain_d3d12.h>
#include "mfg_settings_contract.h"
int _fltused;
static HANDLE out;
static void say(const char*s){DWORD n;WriteFile(out,s,(DWORD)strlen(s),&n,NULL);}
static HMODULE owner(const void*address){
 HMODULE module=NULL;GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,(LPCSTR)address,&module);return module;
}
void mainCRTStartup(void){
 out=GetStdHandle(STD_OUTPUT_HANDLE);char line[600],name[MAX_PATH];
 HMODULE fg=LoadLibraryA("libxess_fg.dll");
 if(!fg){snprintf(line,sizeof(line),"LOAD_FAILED error=%lu\n",GetLastError());say(line);ExitProcess(2);}
 GetModuleFileNameA(fg,name,sizeof(name));snprintf(line,sizeof(line),"LOADED %s\n",name);say(line);
 char flag[8]={0};
 if(GetEnvironmentVariableA("PROXY_CHECK_FORWARDERS",flag,sizeof(flag))&&flag[0]=='1'){
  __typeof__(&xefgSwapChainGetVersion) version=(void*)GetProcAddress(fg,"xefgSwapChainGetVersion");
  xefg_swapchain_version_t v={0};int r=version?version(&v):-9999;HMODULE target=version?owner((void*)version):NULL;
  name[0]=0;if(target)GetModuleFileNameA(target,name,sizeof(name));
  snprintf(line,sizeof(line),"FORWARDED xefgSwapChainGetVersion result=%d version=%u.%u.%u module=%s in_proxy=%d\n",r,v.major,v.minor,v.patch,name,target==fg);say(line);
 }
 __typeof__(&xefgSwapChainD3D12CreateContext) create=(void*)GetProcAddress(fg,"xefgSwapChainD3D12CreateContext");
 xefg_swapchain_handle_t handle=NULL;int r=create?create(NULL,&handle):-9999;
 HMODULE original=GetModuleHandleA("bc250_xefg_original.dll");
 snprintf(line,sizeof(line),"WRAPPED xefgSwapChainD3D12CreateContext(NULL) result=%d in_proxy=%d original_loaded=%d\n",r,create&&owner((void*)create)==fg,original!=NULL);say(line);
 BOOL(WINAPI*get)(struct bc250_fg_status*)=(void*)GetProcAddress(fg,"BC250MFGGetFrameSettings");
 struct bc250_fg_status status={.size=sizeof(status),.version=BC250_FG_SETTINGS_VERSION};BOOL ok=get&&get(&status);
 snprintf(line,sizeof(line),"SETTINGS ok=%d ready=%u resolution=%u downscale_mask=%u upscale_mask=%u\n",ok,status.ready,status.applied.resolution,status.downscale_mask,status.upscale_mask);say(line);
 /* A folder staged for the SDK probes (release/stage_proxy_probe.py) also has the harness stand-in BC250-MFG.asi. */
 HMODULE shim=GetFileAttributesA("BC250-MFG.asi")!=INVALID_FILE_ATTRIBUTES?LoadLibraryA(".\\BC250-MFG.asi"):NULL;
 if(shim){
  BOOL(WINAPI*init)(void)=(void*)GetProcAddress(shim,"BC250MFGInitialize");BOOL(WINAPI*query)(struct bc250_fg_status*)=(void*)GetProcAddress(shim,"BC250MFGGetFrameSettings");
  struct bc250_fg_status via={.size=sizeof(via),.version=BC250_FG_SETTINGS_VERSION};BOOL ready=init&&init(),answered=query&&query(&via);
  snprintf(line,sizeof(line),"SHIM initialize=%d settings=%d forwarded_to_proxy=%d\n",ready,answered,query&&owner((void*)query)==fg);say(line);
 }
 snprintf(line,sizeof(line),"ENABLER version_dll_loaded=%d\n",GetModuleHandleA("version.dll")!=NULL);say(line);
 say("DONE\n");ExitProcess(0);
}
