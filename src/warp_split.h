/* Private same-position split: no reordering, new resource or queue ownership. */
static UINT warp_split_requested,warp_split_count;
static UINT64 warp_split_calls;
static struct{ID3D12PipelineState*original,*motion,*rest;} warp_split_psos[8];
static __attribute__((noinline)) void warp_split_configure(void){
 if(!*patchdir)return;char path[1400];snprintf(path,sizeof(path),"%s\\warp-split.required",patchdir);
 FILE*f=fopen(path,"r");if(!f)return;int c=fgetc(f);fclose(f);if(c!='1')ExitProcess(61);warp_split_requested=1;
}
static ID3D12PipelineState*warp_split_pipeline(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,const char*name){
 char path[1400],line[200];snprintf(path,sizeof(path),"%s\\%s",patchdir,name);
 HANDLE f=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);if(f==INVALID_HANDLE_VALUE)ExitProcess(61);
 DWORD size=GetFileSize(f,NULL),n;if(!size||size>16*1024*1024)ExitProcess(61);void*bytes=malloc(size);
 if(!bytes||!ReadFile(f,bytes,size,&n,NULL)||n!=size)ExitProcess(61);CloseHandle(f);
 D3D12_COMPUTE_PIPELINE_STATE_DESC copy=*desc;copy.CS=(D3D12_SHADER_BYTECODE){bytes,size};copy.CachedPSO=(D3D12_CACHED_PIPELINE_STATE){0};ID3D12PipelineState*p=NULL;
 HR(compute_original(d,&copy,&IID_ID3D12PipelineState,(void**)&p));
 snprintf(line,sizeof(line),"WARP_SPLIT_HELPER name=%s hash=%016llx\n",name,(unsigned long long)hash(bytes,size));logline(line);free(bytes);return p;
}
static void warp_split_capture(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,uint64_t shader,void*original){
 if(!warp_split_requested||shader!=0x3a7d9dfa831ba4f3ULL)return;if(warp_split_count==8)ExitProcess(61);
 UINT i=warp_split_count++;warp_split_psos[i].original=original;
 warp_split_psos[i].motion=warp_split_pipeline(d,desc,"warp-motion.dxil");
 warp_split_psos[i].rest=warp_split_pipeline(d,desc,"warp-rest.dxil");
}
