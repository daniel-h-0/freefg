/* SPDX-License-Identifier: MIT
 * CPU-only check of the enabler-free libxess_fg.dll proxy under Wine (release/check_proxy_wine.py): Windows' loader resolves
 * its export forwarders to bc250_xefg_original.dll, its wrapped entry reaches Intel's runtime only after the size and hash
 * check, and its settings exports answer. No D3D12 device is created and no GPU work is submitted.
 * PROXY_CHECK_FORWARDERS=1 also calls xefgSwapChainGetVersion first (the multi-frame proxy's own tail-calling entry: it
 * verifies and loads the runtime) and, after the wrapped call, resolves xefgAILGetVersion (an export Intel's headers do
 * not declare, still a forwarder) without calling it. PROXY_CHECK_FORWARDER_FIRST=1 resolves that forwarder before
 * anything else, as a caller that looks up every entry at load time does. PROXY_CHECK_PATH loads the proxy from another
 * path (a subfolder, as OptiScaler's own folder). PROXY_CHECK_GAME_RUNTIME=1 first loads a game's own copy of Intel's
 * runtime as libxess_fg.dll beside the program and points its entries at the stub: the proxy must never call it.
 * PROXY_CHECK_HOOKS=1 (the multi-frame proxy) then stands in for another module that hooks Intel's runtime: it writes a
 * jump at eight of Intel's entries in this process to a stub that records its return address and returns -77, and calls
 * the proxy's entries: the lifecycle ones, D3D12GetSwapChainPtr and TagFrameConstants must reach the stub with this
 * program as the caller (tail calls), GetLastPresentStatus and SetNumInterpolatedFrames with the proxy as the caller
 * (ordinary calls), each with one stub call (no status read for a NULL handle). CreateContext gets a device pointer the
 * proxy must not use: this program's call is not OptiScaler's, so the proxy logs that it is not accelerated and never
 * looks at the device. The stand-in modules beside the program (test_proxy_caller.c, built with a version resource)
 * then call CreateContext themselves: the one whose product is OptiScaler must reach the proxy's candidate check
 * (CONTEXT_CALLER in the log; BC250_XEFG_DISABLE=1 ends it there, before the device is used), the other must not, and
 * the stub must see each module as the caller.
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
static void*volatile stub_caller;static volatile LONG stub_calls;
static __attribute__((noinline)) int stub(void){stub_caller=__builtin_return_address(0);InterlockedIncrement(&stub_calls);return -77;}
#define HOOKED 8
static const char*const hooked_names[HOOKED]={"xefgSwapChainD3D12CreateContext","xefgSwapChainD3D12InitFromSwapChain",
 "xefgSwapChainD3D12InitFromSwapChainDesc","xefgSwapChainDestroy","xefgSwapChainTagFrameConstants",
 "xefgSwapChainGetLastPresentStatus","xefgSwapChainSetNumInterpolatedFrames","xefgSwapChainD3D12GetSwapChainPtr"};
static void*fake_device[8];  /* a device pointer the proxy must never use (see above) */
/* An absolute jump (FF 25, then the target) over the entry's first 14 bytes, as an inline hook writes one. */
static int hook_entry(HMODULE runtime,const char*name){
 unsigned char*entry=(void*)GetProcAddress(runtime,name);DWORD old;if(!entry||!VirtualProtect(entry,14,PAGE_EXECUTE_READWRITE,&old))return 0;
 static const unsigned char jump[6]={0xff,0x25,0,0,0,0};void*target=(void*)stub;memcpy(entry,jump,6);memcpy(entry+6,&target,8);
 VirtualProtect(entry,14,old,&old);FlushInstructionCache(GetCurrentProcess(),entry,14);return 1;
}
static void hooked_call(HMODULE fg,int which){
 char line[300];void*p=(void*)GetProcAddress(fg,hooked_names[which]);int r=-9999;stub_caller=NULL;stub_calls=0;
 xefg_swapchain_present_status_t status={0};
 if(p)switch(which){
  case 0:{xefg_swapchain_handle_t h=NULL;r=((__typeof__(&xefgSwapChainD3D12CreateContext))p)((ID3D12Device*)fake_device,&h);break;}
  case 1:r=((__typeof__(&xefgSwapChainD3D12InitFromSwapChain))p)(NULL,NULL,NULL);break;
  case 2:r=((__typeof__(&xefgSwapChainD3D12InitFromSwapChainDesc))p)(NULL,NULL,NULL,NULL,NULL,NULL,NULL);break;
  case 3:r=((__typeof__(&xefgSwapChainDestroy))p)(NULL);break;
  case 4:r=((__typeof__(&xefgSwapChainTagFrameConstants))p)(NULL,0,NULL);break;
  case 5:r=((__typeof__(&xefgSwapChainGetLastPresentStatus))p)(NULL,&status);break;
  case 6:r=((__typeof__(&xefgSwapChainSetNumInterpolatedFrames))p)(NULL,2);break;
  case 7:{static const GUID none;void*chain=NULL;r=((__typeof__(&xefgSwapChainD3D12GetSwapChainPtr))p)(NULL,&none,&chain);break;}
 }
 snprintf(line,sizeof(line),"HOOKED %s result=%d caller_in_program=%d caller_in_proxy=%d calls=%ld\n",hooked_names[which],r,
          stub_caller&&owner(stub_caller)==GetModuleHandleA(NULL),stub_caller&&owner(stub_caller)==fg,stub_calls);say(line);
}
/* A stand-in module (test_proxy_caller.c) calls the proxy's CreateContext. */
static void caller_call(HMODULE fg,const char*module){
 char line[300];HMODULE m=LoadLibraryA(module);int r=-9999;stub_caller=NULL;stub_calls=0;
 int(*create)(void*,ID3D12Device*,xefg_swapchain_handle_t*)=m?(void*)GetProcAddress(m,"ProxyCheckCreate"):NULL;
 xefg_swapchain_handle_t h=NULL;if(create)r=create((void*)GetProcAddress(fg,"xefgSwapChainD3D12CreateContext"),(ID3D12Device*)fake_device,&h);
 snprintf(line,sizeof(line),"CALLER %s loaded=%d result=%d caller_in_module=%d calls=%ld\n",module,m!=NULL,r,m&&stub_caller&&owner(stub_caller)==m,stub_calls);say(line);
}
/* Where an export of the proxy resolves to (the module of its address), without calling it. */
static void resolved(HMODULE fg,const char*label,const char*export){
 char line[600],name[MAX_PATH]={0};void*p=(void*)GetProcAddress(fg,export);HMODULE m=p?owner(p):NULL;if(m)GetModuleFileNameA(m,name,sizeof(name));
 snprintf(line,sizeof(line),"%s %s found=%d module=%s in_proxy=%d\n",label,export,p!=NULL,name,m==fg);say(line);
}
void mainCRTStartup(void){
 out=GetStdHandle(STD_OUTPUT_HANDLE);char line[600],name[MAX_PATH],path[MAX_PATH]="libxess_fg.dll";
 char flag[8]={0};HMODULE game=NULL;
 if(GetEnvironmentVariableA("PROXY_CHECK_GAME_RUNTIME",flag,sizeof(flag))&&flag[0]=='1'){
  game=LoadLibraryA("libxess_fg.dll");int all=game!=NULL;for(int i=0;i<HOOKED&&game;i++)all&=hook_entry(game,hooked_names[i]);
  stub_calls=0;snprintf(line,sizeof(line),"GAME_RUNTIME loaded=%d hooked=%d\n",game!=NULL,all);say(line);
 }
 DWORD length=GetEnvironmentVariableA("PROXY_CHECK_PATH",path,sizeof(path));if(!length||length>=sizeof(path))strcpy(path,"libxess_fg.dll");
 HMODULE fg=LoadLibraryA(path);
 if(!fg){snprintf(line,sizeof(line),"LOAD_FAILED error=%lu\n",GetLastError());say(line);ExitProcess(2);}
 GetModuleFileNameA(fg,name,sizeof(name));snprintf(line,sizeof(line),"LOADED %s\n",name);say(line);
 if(GetEnvironmentVariableA("PROXY_CHECK_FORWARDER_FIRST",flag,sizeof(flag))&&flag[0]=='1')resolved(fg,"FORWARDER_FIRST","xefgAILGetVersion");
 int forwarders=GetEnvironmentVariableA("PROXY_CHECK_FORWARDERS",flag,sizeof(flag))&&flag[0]=='1';
 if(forwarders){
  __typeof__(&xefgSwapChainGetVersion) version=(void*)GetProcAddress(fg,"xefgSwapChainGetVersion");
  xefg_swapchain_version_t v={0};int r=version?version(&v):-9999;HMODULE target=version?owner((void*)version):NULL;
  snprintf(line,sizeof(line),"TAILED xefgSwapChainGetVersion result=%d version=%u.%u.%u in_proxy=%d\n",r,v.major,v.minor,v.patch,target==fg);say(line);
 }
 __typeof__(&xefgSwapChainD3D12CreateContext) create=(void*)GetProcAddress(fg,"xefgSwapChainD3D12CreateContext");
 xefg_swapchain_handle_t handle=NULL;int r=create?create(NULL,&handle):-9999;
 HMODULE original=GetModuleHandleA("bc250_xefg_original.dll");
 snprintf(line,sizeof(line),"WRAPPED xefgSwapChainD3D12CreateContext(NULL) result=%d in_proxy=%d original_loaded=%d\n",r,create&&owner((void*)create)==fg,original!=NULL);say(line);
 /* A second call: a refused runtime is not checked again (one log line, no second 22 MB hash). */
 r=create?create(NULL,&handle):-9999;snprintf(line,sizeof(line),"WRAPPED_AGAIN result=%d\n",r);say(line);
 if(forwarders)resolved(fg,"FORWARDED","xefgAILGetVersion");
 if(game){snprintf(line,sizeof(line),"GAME_RUNTIME stub_calls=%ld\n",stub_calls);say(line);}
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
 if(GetEnvironmentVariableA("PROXY_CHECK_HOOKS",flag,sizeof(flag))&&flag[0]=='1'&&original){
  int all=1;for(int i=0;i<HOOKED;i++)all&=hook_entry(original,hooked_names[i]);
  snprintf(line,sizeof(line),"HOOKS written=%d\n",all);say(line);
  SetEnvironmentVariableA("BC250_XEFG_DISABLE","1");  /* a context that reaches the candidate check stops there */
  for(int i=0;i<HOOKED;i++)hooked_call(fg,i);
  caller_call(fg,"stand_in_optiscaler.dll");caller_call(fg,"stand_in_other.dll");
 }
 snprintf(line,sizeof(line),"ENABLER version_dll_loaded=%d\n",GetModuleHandleA("version.dll")!=NULL);say(line);
 say("DONE\n");ExitProcess(0);
}
