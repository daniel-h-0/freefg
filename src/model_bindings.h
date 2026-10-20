/* Probe-only descriptor provenance for model_owner.h. */
static struct {SIZE_T cpu;struct model_record*m;} model_descriptors[8192];static UINT model_descriptor_count;
static struct {ID3D12DescriptorHeap*h;SIZE_T cpu;UINT64 gpu;UINT count,stride;} model_heaps[128];static UINT model_heap_count;
static struct {ID3D12GraphicsCommandList*l;ID3D12RootSignature*root;UINT64 table,table0;UINT constants[12],constant_mask;} model_lists[128];static UINT model_list_count;
/* SDK startup/resizing can create additional matching roots after initialization.
 * Retain their identities until context teardown, including the layout guard. */
#define MODEL_ROOT_CAPACITY 256
static ID3D12RootSignature*model_roots[MODEL_ROOT_CAPACITY];static UINT model_root_count;
static UINT model_graph_roots[MODEL_ROOT_CAPACITY];
static UINT model_known_root(ID3D12RootSignature*r){for(UINT i=0;i<model_root_count;i++)if(model_roots[i]==r)return 1;return 0;}
static __typeof__(heap_original) model_heap_original;
static __typeof__(simple_original) model_simple_original;
static __typeof__(descs_original) model_descs_original;
static __typeof__(table_original) model_table_original;
static __typeof__(set_root_original) model_root_original;
static __typeof__(cbv_original) model_cbv_original;
static struct model_record*model_descriptor_get(SIZE_T cpu){for(UINT i=0;i<model_descriptor_count;i++)if(model_descriptors[i].cpu==cpu)return model_descriptors[i].m;return NULL;}
static void model_descriptor_set(SIZE_T cpu,struct model_record*m){UINT i;for(i=0;i<model_descriptor_count;i++)if(model_descriptors[i].cpu==cpu)break;if(i==model_descriptor_count){if(!m)return;if(i==8192)model_fail("descriptor tracking capacity");model_descriptor_count++;model_descriptors[i].cpu=cpu;}
 if(!m){model_descriptors[i]=model_descriptors[--model_descriptor_count];memset(&model_descriptors[model_descriptor_count],0,sizeof(*model_descriptors));return;}
 model_descriptors[i].m=m;}
static UINT model_list(ID3D12GraphicsCommandList*l){UINT i;for(i=0;i<model_list_count;i++)if(model_lists[i].l==l)break;if(i==model_list_count){if(i==128)model_fail("list tracking capacity");model_lists[i].l=l;model_list_count++;}return i;}
static void model_root_check(ID3D12RootSignature*r){
 /* The pinned FEC root has its t1/t2/t3 SRVs at table1 offsets0/1/2.
  * A blob-level root layout check is done at CreateRootSignature below. */
 if(!model_owner_enabled)return;
 AcquireSRWLockShared(&model_lock);
 if(!model_known_root(r)){char line[180];snprintf(line,sizeof(line),"MODEL_UNKNOWN_ROOT pointer=%p known=%u\n",r,model_root_count);logline(line);model_fail("FEC root layout was not recognized");}
 ReleaseSRWLockShared(&model_lock);
}
static __typeof__(root_original) model_create_root_original;
#include "mfg_root_cache.h"
static HRESULT STDMETHODCALLTYPE model_create_root_hook(ID3D12Device*d,UINT node,const void*data,SIZE_T size,REFIID iid,void**out){
 HRESULT(WINAPI*deserialize)(const void*,SIZE_T,REFIID,void**)=(void*)GetProcAddress(GetModuleHandleA("d3d12.dll"),"D3D12CreateVersionedRootSignatureDeserializer");
 ID3D12VersionedRootSignatureDeserializer*reader=NULL;const D3D12_VERSIONED_ROOT_SIGNATURE_DESC*desc=NULL;
 if(!deserialize||FAILED(deserialize(data,size,&IID_ID3D12VersionedRootSignatureDeserializer,(void**)&reader)))model_fail("root deserialization");
 HR(ID3D12VersionedRootSignatureDeserializer_GetRootSignatureDescAtVersion(reader,D3D_ROOT_SIGNATURE_VERSION_1_0,&desc));
 const D3D12_ROOT_SIGNATURE_DESC*s=&desc->Desc_1_0;
 UINT match=s->NumParameters==3&&s->pParameters[1].ParameterType==D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE&&s->pParameters[2].ParameterType==D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS&&(s->pParameters[2].Constants.Num32BitValues==12||(model_owner_enabled>=2&&s->pParameters[2].Constants.Num32BitValues==4));
 if(match){const D3D12_ROOT_DESCRIPTOR_TABLE*t=&s->pParameters[1].DescriptorTable;match=t->NumDescriptorRanges==3;for(UINT i=0;match&&i<3;i++){const D3D12_DESCRIPTOR_RANGE*v=&t->pDescriptorRanges[i];match=v->RangeType==D3D12_DESCRIPTOR_RANGE_TYPE_SRV&&v->NumDescriptors==1&&v->BaseShaderRegister==i+1&&v->RegisterSpace==0&&(v->OffsetInDescriptorsFromTableStart==D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND||v->OffsetInDescriptorsFromTableStart==i);}}
 UINT graph=match&&s->Flags==D3D12_ROOT_SIGNATURE_FLAG_NONE&&s->NumStaticSamplers==0&&s->pParameters[0].ParameterType==D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE&&s->pParameters[2].Constants.Num32BitValues==12&&s->pParameters[2].Constants.ShaderRegister==0&&s->pParameters[2].Constants.RegisterSpace==0;
 if(graph){for(UINT i=0;i<3;i++)graph&=s->pParameters[i].ShaderVisibility==D3D12_SHADER_VISIBILITY_ALL;const D3D12_ROOT_DESCRIPTOR_TABLE*t=&s->pParameters[0].DescriptorTable;graph&=t->NumDescriptorRanges==2;for(UINT i=0;graph&&i<2;i++){const D3D12_DESCRIPTOR_RANGE*v=&t->pDescriptorRanges[i];graph=v->RangeType==(i?D3D12_DESCRIPTOR_RANGE_TYPE_UAV:D3D12_DESCRIPTOR_RANGE_TYPE_SRV)&&v->NumDescriptors==1&&v->BaseShaderRegister==0&&v->RegisterSpace==0&&(v->OffsetInDescriptorsFromTableStart==D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND||v->OffsetInDescriptorsFromTableStart==i);}}
 UINT expanded=graph&&model_owner_enabled==7
 ;ID3DBlob*blob=NULL;
 if(expanded){
  D3D12_ROOT_PARAMETER parameters[5]={0};memcpy(parameters,s->pParameters,3*sizeof(*parameters));
  for(UINT i=3;i<5;i++){parameters[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV;parameters[i].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;parameters[i].Descriptor.ShaderRegister=i-2;}
  D3D12_ROOT_SIGNATURE_DESC extended=*s;extended.NumParameters=5;extended.pParameters=parameters;
  HRESULT(WINAPI*serialize)(const D3D12_ROOT_SIGNATURE_DESC*,D3D_ROOT_SIGNATURE_VERSION,ID3DBlob**,ID3DBlob**)=(void*)GetProcAddress(GetModuleHandleA("d3d12.dll"),"D3D12SerializeRootSignature");
  if(!serialize)model_fail("missing root serializer");HR(serialize(&extended,D3D_ROOT_SIGNATURE_VERSION_1_0,&blob,NULL));data=ID3D10Blob_GetBufferPointer(blob);size=ID3D10Blob_GetBufferSize(blob);
 }
 HRESULT hr=
 mfg_cached_root(d,node,data,size,iid,out);
 if(blob)ID3D10Blob_Release(blob);
 if(SUCCEEDED(hr)&&match){AcquireSRWLockExclusive(&model_lock);if(!model_known_root(*out)){if(model_root_count==MODEL_ROOT_CAPACITY)model_fail("root tracking capacity");UINT index=model_root_count++;model_roots[index]=*out;model_graph_roots[index]=expanded;ID3D12RootSignature_AddRef((ID3D12RootSignature*)*out);}ReleaseSRWLockExclusive(&model_lock);}
 if(SUCCEEDED(hr)&&expanded)logline("WINOGRAD_ROOT preserved three parameters; appended u1/u2 roots\n");
 ID3D12VersionedRootSignatureDeserializer_Release(reader);return hr;
}
static void mfg_watch_descriptor_heap(ID3D12Device*,ID3D12DescriptorHeap*,const D3D12_DESCRIPTOR_HEAP_DESC*);
static HRESULT STDMETHODCALLTYPE model_heap_hook(ID3D12Device*d,const D3D12_DESCRIPTOR_HEAP_DESC*desc,REFIID iid,void**out){
 HRESULT hr=model_heap_original(d,desc,iid,out);
 if(SUCCEEDED(hr)&&desc->Type==D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV)mfg_watch_descriptor_heap(d,*out,desc);
 return hr;
}
static void STDMETHODCALLTYPE model_simple_hook(ID3D12Device*d,UINT n,D3D12_CPU_DESCRIPTOR_HANDLE dst,D3D12_CPU_DESCRIPTOR_HANDLE src,D3D12_DESCRIPTOR_HEAP_TYPE type){
 if(type==D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV){UINT step=ID3D12Device_GetDescriptorHandleIncrementSize(d,type);AcquireSRWLockExclusive(&model_lock);for(UINT i=0;i<n;i++)model_descriptor_set(dst.ptr+i*step,model_descriptor_get(src.ptr+i*step));ReleaseSRWLockExclusive(&model_lock);}model_simple_original(d,n,dst,src,type);
}
static void STDMETHODCALLTYPE model_descs_hook(ID3D12Device*d,UINT nd,const D3D12_CPU_DESCRIPTOR_HANDLE*dst,const UINT*dn,UINT ns,const D3D12_CPU_DESCRIPTOR_HANDLE*src,const UINT*sn,D3D12_DESCRIPTOR_HEAP_TYPE type){
 if(type==D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV){UINT si=0,so=0,step=ID3D12Device_GetDescriptorHandleIncrementSize(d,type);AcquireSRWLockExclusive(&model_lock);for(UINT di=0;di<nd;di++)for(UINT off=0;off<(dn?dn[di]:1);off++){if(si>=ns)model_fail("invalid descriptor copy");model_descriptor_set(dst[di].ptr+off*step,model_descriptor_get(src[si].ptr+so*step));if(++so==(sn?sn[si]:1)){si++;so=0;}}ReleaseSRWLockExclusive(&model_lock);}model_descs_original(d,nd,dst,dn,ns,src,sn,type);
}
static void STDMETHODCALLTYPE model_table_hook(ID3D12GraphicsCommandList*l,UINT index,D3D12_GPU_DESCRIPTOR_HANDLE h){if(index<=1){AcquireSRWLockExclusive(&model_lock);UINT i=model_list(l);if(index==1)model_lists[i].table=h.ptr;else model_lists[i].table0=h.ptr;ReleaseSRWLockExclusive(&model_lock);}model_table_original(l,index,h);}
static void STDMETHODCALLTYPE model_set_root_hook(ID3D12GraphicsCommandList*l,ID3D12RootSignature*r){AcquireSRWLockExclusive(&model_lock);UINT i=model_list(l);if(model_lists[i].root!=r){model_lists[i].table=0;model_lists[i].table0=0;model_lists[i].constant_mask=0;}model_lists[i].root=r;ReleaseSRWLockExclusive(&model_lock);model_root_original(l,r);}
static void STDMETHODCALLTYPE model_cbv_hook(ID3D12Device*d,const D3D12_CONSTANT_BUFFER_VIEW_DESC*desc,D3D12_CPU_DESCRIPTOR_HANDLE h){AcquireSRWLockExclusive(&model_lock);model_descriptor_set(h.ptr,NULL);ReleaseSRWLockExclusive(&model_lock);model_cbv_original(d,desc,h);}
static void model_binding_check(ID3D12GraphicsCommandList*l,UINT bytes){
 UINT i=model_list(l);if(!model_known_root(model_lists[i].root)||!model_lists[i].table)model_fail("missing FEC model table");UINT64 gpu=model_lists[i].table;
 for(UINT h=0;h<model_heap_count;h++){UINT64 base=model_heaps[h].gpu,heap_bytes=(UINT64)model_heaps[h].count*model_heaps[h].stride;if(gpu>=base&&gpu-base<heap_bytes&&(gpu-base)%model_heaps[h].stride==0){struct model_record*m=model_descriptor_get(model_heaps[h].cpu+(SIZE_T)(gpu-base));if(!m||!m->initialized||m->bytes!=bytes){char line[300];snprintf(line,sizeof(line),"MODEL_BAD_BIND list=%p root=%p gpu=%llx cpu=%llx expected=%u model=%p bytes=%u initialized=%u heaps=%u descriptors=%u\n",l,model_lists[i].root,(unsigned long long)gpu,(unsigned long long)(model_heaps[h].cpu+(SIZE_T)(gpu-base)),bytes,m,m?m->bytes:0,m?m->initialized:0,model_heap_count,model_descriptor_count);logline(line);model_fail("FEC reads an unowned coefficient descriptor");}return;}}
 model_fail("FEC table outside tracked heaps");
}
static __typeof__(constants_original) model_constants_original;
static void(STDMETHODCALLTYPE*model_constant_original)(ID3D12GraphicsCommandList*,UINT,UINT,UINT);
static HRESULT(STDMETHODCALLTYPE*model_reset_original)(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*);
static void model_track_constants(ID3D12GraphicsCommandList*l,UINT index,UINT count,const UINT*values,UINT offset){
 if(index!=2||offset>12||count>12-offset)return;
 AcquireSRWLockExclusive(&model_lock);UINT i=model_list(l);for(UINT n=0;n<count;n++){model_lists[i].constants[offset+n]=values[n];model_lists[i].constant_mask|=1u<<(offset+n);}ReleaseSRWLockExclusive(&model_lock);
}
static void STDMETHODCALLTYPE model_constants_hook(ID3D12GraphicsCommandList*l,UINT index,UINT count,const void*values,UINT offset){model_track_constants(l,index,count,values,offset);model_constants_original(l,index,count,values,offset);}
static void STDMETHODCALLTYPE model_constant_hook(ID3D12GraphicsCommandList*l,UINT index,UINT value,UINT offset){model_track_constants(l,index,1,&value,offset);model_constant_original(l,index,value,offset);}
static HRESULT STDMETHODCALLTYPE model_reset_hook(ID3D12GraphicsCommandList*l,ID3D12CommandAllocator*a,ID3D12PipelineState*p){HRESULT hr=model_reset_original(l,a,p);if(SUCCEEDED(hr)){AcquireSRWLockExclusive(&model_lock);UINT i=model_list(l);model_lists[i].root=NULL;model_lists[i].table=model_lists[i].table0=0;model_lists[i].constant_mask=0;ReleaseSRWLockExclusive(&model_lock);}return hr;}
static void install_model_bindings(ID3D12Device*d,ID3D12GraphicsCommandList*l){
 if(model_owner_enabled==7){
  model_constants_original=l->lpVtbl->SetComputeRoot32BitConstants;replace((void*)&l->lpVtbl->SetComputeRoot32BitConstants,model_constants_hook);
  model_constant_original=l->lpVtbl->SetComputeRoot32BitConstant;replace((void*)&l->lpVtbl->SetComputeRoot32BitConstant,model_constant_hook);
  model_reset_original=l->lpVtbl->Reset;replace((void*)&l->lpVtbl->Reset,model_reset_hook);
 }
 model_create_root_original=d->lpVtbl->CreateRootSignature;replace((void*)&d->lpVtbl->CreateRootSignature,model_create_root_hook);
 model_heap_original=d->lpVtbl->CreateDescriptorHeap;replace((void*)&d->lpVtbl->CreateDescriptorHeap,model_heap_hook);
 model_simple_original=d->lpVtbl->CopyDescriptorsSimple;replace((void*)&d->lpVtbl->CopyDescriptorsSimple,model_simple_hook);
 model_descs_original=d->lpVtbl->CopyDescriptors;replace((void*)&d->lpVtbl->CopyDescriptors,model_descs_hook);
 model_table_original=l->lpVtbl->SetComputeRootDescriptorTable;replace((void*)&l->lpVtbl->SetComputeRootDescriptorTable,model_table_hook);
 model_root_original=l->lpVtbl->SetComputeRootSignature;replace((void*)&l->lpVtbl->SetComputeRootSignature,model_set_root_hook);
 model_cbv_original=d->lpVtbl->CreateConstantBufferView;replace((void*)&d->lpVtbl->CreateConstantBufferView,model_cbv_hook);
}
