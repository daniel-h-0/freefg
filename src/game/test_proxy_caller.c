/* SPDX-License-Identifier: MIT
 * A stand-in for a module that calls the multi-frame proxy's xefgSwapChainD3D12CreateContext from its own code, for the
 * Wine loader check (release/check_proxy_wine.py builds it twice, with a version resource whose product is OptiScaler
 * and with one whose product is something else; src/game/test_proxy_load.c loads both). The call is never a tail call,
 * so the proxy sees this module as its caller. No D3D12 device is created: the device pointer is passed through.
 */
#include <windows.h>
#include <xefg_swapchain_d3d12.h>
__declspec(dllexport) __attribute__((noinline,disable_tail_calls)) int ProxyCheckCreate(void*create,ID3D12Device*device,
                                                                                      xefg_swapchain_handle_t*out){
 return ((__typeof__(&xefgSwapChainD3D12CreateContext))create)(device,out);
}
BOOL WINAPI DllMainCRTStartup(HINSTANCE instance,DWORD reason,LPVOID reserved){(void)instance;(void)reason;(void)reserved;return TRUE;}
