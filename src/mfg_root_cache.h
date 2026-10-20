/* SPDX-License-Identifier: MIT
 * Canonical SDK-private root signatures, compared by complete serialized bytes.
 * Each returned reference belongs to the SDK; one extra cache ref lasts to teardown.
 */
static struct{ID3D12RootSignature*r;void*bytes;SIZE_T size;UINT node;}mfg_roots[128];
static UINT mfg_root_cache_count;
static HRESULT mfg_cached_root(ID3D12Device*d,UINT node,const void*data,SIZE_T size,REFIID iid,void**out){
 if(!IsEqualGUID(iid,&IID_ID3D12RootSignature))return model_create_root_original(d,node,data,size,iid,out);
 AcquireSRWLockExclusive(&model_lock);
 for(UINT i=0;i<mfg_root_cache_count;i++)if(mfg_roots[i].node==node&&mfg_roots[i].size==size&&!memcmp(mfg_roots[i].bytes,data,size)){
  ID3D12RootSignature_AddRef(mfg_roots[i].r);*out=mfg_roots[i].r;ReleaseSRWLockExclusive(&model_lock);return S_OK;
 }
 HRESULT hr=model_create_root_original(d,node,data,size,iid,out);
 if(SUCCEEDED(hr)){if(mfg_root_cache_count==128)model_fail("distinct root cache capacity");UINT i=mfg_root_cache_count++;mfg_roots[i].bytes=malloc(size);if(!mfg_roots[i].bytes)model_fail("root cache allocation");memcpy(mfg_roots[i].bytes,data,size);mfg_roots[i].size=size;mfg_roots[i].node=node;mfg_roots[i].r=*out;ID3D12RootSignature_AddRef(mfg_roots[i].r);}
 ReleaseSRWLockExclusive(&model_lock);return hr;
}
static void mfg_release_roots(void){for(UINT i=0;i<mfg_root_cache_count;i++){ID3D12RootSignature_Release(mfg_roots[i].r);free(mfg_roots[i].bytes);}memset(mfg_roots,0,sizeof(mfg_roots));mfg_root_cache_count=0;}
