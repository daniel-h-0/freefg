/* SPDX-License-Identifier: MIT
 * CPU-only tests of the actual cached-history state transitions. No D3D device,
 * runtime or GPU is used; opaque identities stand for resources and lists.
 */
#define WIDL_C_INLINE_WRAPPERS
#define COBJMACROS
#include <windows.h>
#include <d3d12.h>
#include <stdint.h>
#include <stdio.h>
#include "../frame_scale_history.h"
int _fltused;
static int failures;
static void check(int ok,const char*what,int line){char s[300];int n=snprintf(s,sizeof(s),"%s line=%d: %s\n",ok?"ok":"FAIL",line,what);DWORD w;WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),s,n,&w,NULL);failures+=!ok;}
#define CHECK(x) check((x)!=0,#x,__LINE__)
void mainCRTStartup(void){
 ID3D12Resource*a=(void*)(uintptr_t)0x1000,*b=(void*)(uintptr_t)0x2000,*other=(void*)(uintptr_t)0x3000;
 ID3D12GraphicsCommandList*l1=(void*)(uintptr_t)0x4000,*l2=(void*)(uintptr_t)0x5000;
 struct scale_image i={.source.r=a},j={.source.r=b};i.next=&j;
 /* A reduced application resource never becomes persistent without an SDK copy. */
 i.low_valid=1;i.sampled_list=l1;CHECK(!scale_history_reusable(&i,l1));
 scale_history_copied(&i,a);CHECK(scale_history_reusable(&i,l1));CHECK(!j.copy_preserved);
 /* A pending reduction can be reused within its own list, then across lists
  * only after submission on the already-enforced single owner queue. */
 i.low_pending=1;i.sampled_graph=7;CHECK(scale_history_reusable(&i,l1));CHECK(!scale_history_reusable(&i,l2));
 scale_history_submitted(&i,(ID3D12CommandList*)l2);CHECK(i.low_pending);
 scale_history_submitted(&i,(ID3D12CommandList*)l1);CHECK(!i.low_pending);CHECK(scale_history_reusable(&i,l2));
 scale_history_reset(&i,l1);CHECK(!i.sampled_graph);CHECK(i.low_valid);CHECK(scale_history_reusable(&i,l2));
 /* Abandoning an unsubmitted reduction must revoke it; another list's reset
  * must not discard work that this list still owns. */
 i.low_pending=1;i.sampled_graph=8;scale_history_reset(&i,l2);CHECK(i.low_pending&&i.low_valid&&i.sampled_graph==8);
 scale_history_reset(&i,l1);CHECK(!i.low_pending&&!i.low_valid&&!i.sampled_graph);CHECK(!scale_history_reusable(&i,l1));
 /* Resource writes invalidate every view of that resource, but not an unrelated
  * history. The same resource may have multiple view/size cache entries. */
 struct scale_image k={.source.r=a,.copy_preserved=1,.low_valid=1,.sampled_graph=9};j.next=&k;
 i.copy_preserved=i.low_valid=i.low_pending=1;i.sampled_graph=9;
 j.copy_preserved=j.low_valid=1;j.sampled_graph=9;
 scale_history_written(&i,other);CHECK(i.low_valid&&j.low_valid&&k.low_valid);
 scale_history_written(&i,a);CHECK(!i.low_valid&&!i.low_pending&&!i.copy_preserved&&!i.sampled_graph);CHECK(!k.low_valid&&!k.copy_preserved&&!k.sampled_graph);CHECK(j.low_valid&&j.copy_preserved&&j.sampled_graph==9);
 scale_history_copied(&i,a);CHECK(i.copy_preserved&&k.copy_preserved);CHECK(!i.low_valid&&!k.low_valid);
 /* NULL is the aliasing barrier's wildcard, not a resource identity that can
  * never match. Any potential source alias must revoke every cached version. */
 i.low_valid=k.low_valid=1;i.sampled_graph=k.sampled_graph=10;
 scale_history_written(&i,NULL);CHECK(!i.low_valid&&!j.low_valid&&!k.low_valid);CHECK(!i.copy_preserved&&!j.copy_preserved&&!k.copy_preserved);CHECK(!i.sampled_graph&&!j.sampled_graph&&!k.sampled_graph);
 char s[80];int n=snprintf(s,sizeof(s),"SCALE_HISTORY_UNIT failures=%d\n",failures);DWORD w;WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),s,n,&w,NULL);ExitProcess(failures?1:0);
}
