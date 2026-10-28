/* SPDX-License-Identifier: MIT */
#ifndef FREEFG_FRAME_SCALE_API_H
#define FREEFG_FRAME_SCALE_API_H
static void scale_capture_unet(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,uint64_t,ID3D12PipelineState*,const char*);
static int scale_dispatch_unet(ID3D12GraphicsCommandList*,uint64_t,UINT,UINT,UINT);
static void scale_capture_root(ID3D12RootSignature*,const D3D12_ROOT_SIGNATURE_DESC*);
static void scale_install(UINT);
static UINT scale_begin_graph(ID3D12GraphicsCommandList*);
static int scale_check_bindings(ID3D12GraphicsCommandList*,uint64_t);
static void scale_observation_done(void);
static void scale_invalidate(void);
static void scale_block(const char*);
static void scale_report_full(UINT,UINT);
static ID3D12RootSignature*scale_create_filter_root(UINT);
static int scale_dispatch(ID3D12GraphicsCommandList*,uint64_t,UINT,UINT,UINT);
static void scale_release(void);
static void scale_reset_list(ID3D12GraphicsCommandList*);
static void scale_source_written(ID3D12Resource*);
static void scale_source_copied(ID3D12Resource*);
static void scale_purge_descriptors(SIZE_T,SIZE_T);
static int scale_queue_execute(ID3D12CommandQueue*,UINT,ID3D12CommandList*const*,
 void(STDMETHODCALLTYPE*)(ID3D12CommandQueue*,UINT,ID3D12CommandList*const*));
#endif
