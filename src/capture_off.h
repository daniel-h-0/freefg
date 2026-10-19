/* SPDX-License-Identifier: MIT
 * Game builds of the probe core (XEFG_GAME_CORE: the add-on and the libxess_fg.dll proxy) include this file. They keep
 * only what the shared core still names:
 *   - the D3D12 method slots whose types other core headers take with __typeof__ (never assigned or called in a game
 *     build);
 *   - the dispatch hook's diagnostic DISPATCH line, behind capture_buffers, which a game build never sets, so the
 *     compiler drops the call. Its text stays as it is on purpose: the binaries' symbol tables name string literals by
 *     their order in the source (.str.N), so a shorter function would renumber them and change the output bytes;
 *   - no-op versions of the core's two other per-dispatch diagnostics (constant override and output tap). The release
 *     builds remove both calls from the core (release/build_addon.py PROBE_PATCHES); a game build that keeps them links
 *     these.
 */
static HRESULT(STDMETHODCALLTYPE*root_original)(ID3D12Device*,UINT,const void*,SIZE_T,REFIID,void**);
static HRESULT(STDMETHODCALLTYPE*committed_original)(ID3D12Device*,const D3D12_HEAP_PROPERTIES*,D3D12_HEAP_FLAGS,const D3D12_RESOURCE_DESC*,D3D12_RESOURCE_STATES,const D3D12_CLEAR_VALUE*,REFIID,void**);
static HRESULT(STDMETHODCALLTYPE*placed_original)(ID3D12Device*,ID3D12Heap*,UINT64,const D3D12_RESOURCE_DESC*,D3D12_RESOURCE_STATES,const D3D12_CLEAR_VALUE*,REFIID,void**);
static void(STDMETHODCALLTYPE*copy_original)(ID3D12GraphicsCommandList*,ID3D12Resource*,UINT64,ID3D12Resource*,UINT64,UINT64);
static void(STDMETHODCALLTYPE*srv_original)(ID3D12Device*,ID3D12Resource*,const D3D12_SHADER_RESOURCE_VIEW_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE);
static void(STDMETHODCALLTYPE*uav_original)(ID3D12Device*,ID3D12Resource*,ID3D12Resource*,const D3D12_UNORDERED_ACCESS_VIEW_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE);
static void(STDMETHODCALLTYPE*cbv_original)(ID3D12Device*,const D3D12_CONSTANT_BUFFER_VIEW_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE);
static void(STDMETHODCALLTYPE*copy_texture_original)(ID3D12GraphicsCommandList*,const D3D12_TEXTURE_COPY_LOCATION*,UINT,UINT,UINT,const D3D12_TEXTURE_COPY_LOCATION*,const D3D12_BOX*);
static void(STDMETHODCALLTYPE*copy_resource_original)(ID3D12GraphicsCommandList*,ID3D12Resource*,ID3D12Resource*);
static void(STDMETHODCALLTYPE*set_root_original)(ID3D12GraphicsCommandList*,ID3D12RootSignature*);
static HRESULT(STDMETHODCALLTYPE*heap_original)(ID3D12Device*,const D3D12_DESCRIPTOR_HEAP_DESC*,REFIID,void**);
static void(STDMETHODCALLTYPE*simple_original)(ID3D12Device*,UINT,D3D12_CPU_DESCRIPTOR_HANDLE,D3D12_CPU_DESCRIPTOR_HANDLE,D3D12_DESCRIPTOR_HEAP_TYPE);
static void(STDMETHODCALLTYPE*descs_original)(ID3D12Device*,UINT,const D3D12_CPU_DESCRIPTOR_HANDLE*,const UINT*,UINT,const D3D12_CPU_DESCRIPTOR_HANDLE*,const UINT*,D3D12_DESCRIPTOR_HEAP_TYPE);
static void(STDMETHODCALLTYPE*table_original)(ID3D12GraphicsCommandList*,UINT,D3D12_GPU_DESCRIPTOR_HANDLE);
static void(STDMETHODCALLTYPE*constants_original)(ID3D12GraphicsCommandList*,UINT,UINT,const void*,UINT);
static int capture_buffers;
static void capture_dispatch(ID3D12GraphicsCommandList*l,uint64_t shader){if(capture_buffers){char line[160];snprintf(line,sizeof(line),"DISPATCH list=%p shader=%016llx frame=%u phase=%s\n",l,(unsigned long long)shader,frame,fsr_recording?"fsr4":"xefg");logline(line);}}
static __attribute__((unused)) void tap_dispatch(ID3D12GraphicsCommandList*l,uint64_t shader){(void)l;(void)shader;}
static __attribute__((unused)) void const_override(ID3D12GraphicsCommandList*l,uint64_t shader){(void)l;(void)shader;}
