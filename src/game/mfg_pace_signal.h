/* SPDX-License-Identifier: MIT
 * Tells the Vulkan pacing layer (libxefg_wave.so, native code in this Wine process) whether XeFG is generating frames,
 * so the layer holds frames for their slots only then and lets FSR 3 FG, games with frame generation off and menus pass
 * straight through. On its first present the layer creates /dev/shm/bc250-xefg-pace-<drive_c inode>-<Windows pid>
 * (both visible here: C:\\ and GetCurrentProcessId; /proc/self would name the wineserver, which opens files for Wine).
 * This thread maps that page through Z: and stores, every 20 ms, a running count that advances for every generated frame
 * (XeFG's final output pass as recorded, plus the accelerated network and warp counters, plus the frames Intel's SDK
 * reports sent after each Present: mfg_xell_pace.h in the enabler build, mfg_proxy_coexist.h in the multi-frame proxy)
 * and a heartbeat. The network counters alone would miss 2x, whose
 * accelerated path is the warp; the SDK status is what moves with Intel's shaders (BC250_XEFG_DISABLE=1, or another GPU
 * without BC250_XEFG_ANY_GPU=1), where no accelerated counter does. The layer holds while the count moved within
 * the last 250 ms. Without the layer the page never appears and the thread only retries once a second. */
#define MFG_PACE_SIGNAL_MAGIC "BC250XP1"
struct mfg_pace_page {char magic[8];volatile UINT64 generated,beat;UINT32 owner;};
static UINT64 mfg_pace_generated(void){
 /* XeFG's final output pass (every generated frame), plus the accelerated network and warp counters as further evidence. */
 UINT64 sum=(UINT64)InterlockedCompareExchange64(&frame_outputs_recorded,0,0)+*(volatile UINT64*)&graph_geometry_fallbacks;
 for(size_t i=0;i<sizeof(graph_counts)/sizeof(graph_counts[0]);i++)sum+=*(volatile UINT64*)&graph_counts[i];
 for(size_t i=0;i<sizeof(graph_ref64_counts)/sizeof(graph_ref64_counts[0]);i++)sum+=*(volatile UINT64*)&graph_ref64_counts[i];
 sum+=(UINT64)InterlockedCompareExchange64(&proxy_status_generated,0,0);  /* the multi-frame proxy's SDK status count */
 return sum;
}
static struct mfg_pace_page*mfg_pace_open(void){
 HANDLE c=CreateFileW(L"C:\\",0,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,NULL,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS,NULL);
 if(c==INVALID_HANDLE_VALUE)return NULL;
 BY_HANDLE_FILE_INFORMATION bi;BOOL ok=GetFileInformationByHandle(c,&bi);CloseHandle(c);if(!ok)return NULL;
 UINT64 ino=((UINT64)bi.nFileIndexHigh<<32)|bi.nFileIndexLow;DWORD pid=GetCurrentProcessId();
 wchar_t path[96]=L"Z:\\dev\\shm\\bc250-xefg-pace-";size_t at=wcslen(path);wchar_t digits[24];int n=0;
 do{unsigned d=(unsigned)(ino&15);digits[n++]=(wchar_t)(d<10?L'0'+d:L'a'+d-10);}while((ino>>=4)&&n<16);
 while(n)path[at++]=digits[--n];path[at++]=L'-';
 do digits[n++]=(wchar_t)(L'0'+pid%10);while((pid/=10)&&n<11);
 while(n)path[at++]=digits[--n];path[at]=0;
 static LONG told;if(!InterlockedExchange(&told,1)){char line[160];snprintf(line,sizeof(line),"MFG pace signal: looking for %ls\n",path);proxy_log(line);}
 HANDLE f=CreateFileW(path,GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,NULL,OPEN_EXISTING,0,NULL);
 if(f==INVALID_HANDLE_VALUE)return NULL;
 HANDLE m=CreateFileMappingW(f,NULL,PAGE_READWRITE,0,4096,NULL);CloseHandle(f);if(!m)return NULL;
 struct mfg_pace_page*p=MapViewOfFile(m,FILE_MAP_READ|FILE_MAP_WRITE,0,0,4096);CloseHandle(m);if(!p)return NULL;
 for(int i=0;i<8;i++)if(p->magic[i]!=MFG_PACE_SIGNAL_MAGIC[i]){UnmapViewOfFile(p);return NULL;}  /* not the layer's page yet */
 return p;
}
static DWORD WINAPI mfg_pace_signal_thread(void*unused){
 (void)unused;struct mfg_pace_page*page=NULL;
 for(unsigned tick=0;;tick++){
  if(!page&&tick%50==0&&(page=mfg_pace_open()))proxy_log("MFG pace signal: telling the pacing layer when XeFG generates frames\n");
  if(page){page->generated=mfg_pace_generated();page->beat++;}
  Sleep(20);
 }
 return 0;
}
static void mfg_pace_signal_start(void){HANDLE t=CreateThread(NULL,0,mfg_pace_signal_thread,NULL,0,NULL);if(t)CloseHandle(t);}
