/* SPDX-License-Identifier: MIT
 * Preserve SDK allocations/uploads; share exact immutable prepared coefficients
 * across backend rebuilds. Hashes are only a filter: every reuse compares bytes.
 * Canonical GPU buffers remain owned until the existing teardown fence completes.
 */
static HRESULT STDMETHODCALLTYPE mfg_pool_placed(ID3D12Device*d,ID3D12Heap*h,UINT64 offset,const D3D12_RESOURCE_DESC*rd,D3D12_RESOURCE_STATES state,const D3D12_CLEAR_VALUE*clear,REFIID iid,void**out){
 UINT selected=rd->Dimension==D3D12_RESOURCE_DIMENSION_BUFFER&&rd->Width<=UINT32_MAX&&rd->Flags==D3D12_RESOURCE_FLAG_NONE&&state==D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE&&model_selected_size((UINT)rd->Width);
 if(selected){D3D12_HEAP_DESC heap=ID3D12Heap_GetDesc(h);
  if(rd->Format!=DXGI_FORMAT_UNKNOWN||rd->Height!=1||rd->DepthOrArraySize!=1||rd->MipLevels!=1||rd->SampleDesc.Count!=1||rd->Layout!=D3D12_TEXTURE_LAYOUT_ROW_MAJOR||clear||heap.Properties.Type!=D3D12_HEAP_TYPE_DEFAULT||!IsEqualGUID(iid,&IID_ID3D12Resource))model_fail("pooled model allocation layout");
 }
 HRESULT hr=model_placed_original(d,h,offset,rd,state,clear,iid,out);if(FAILED(hr)||!selected)return hr;
 AcquireSRWLockExclusive(&model_lock);UINT i;
 for(i=0;i<mfg_alias_count;i++)if(mfg_aliases_owner[i].r==*out)break;
 if(i==mfg_alias_count){
  if(i==mfg_alias_capacity){UINT capacity=mfg_alias_capacity?mfg_alias_capacity*2:128;if(capacity>65536)model_fail("model alias capacity");
   void*p=realloc(mfg_aliases_owner,(size_t)capacity*sizeof(*mfg_aliases_owner));if(!p)model_fail("model alias allocation");mfg_aliases_owner=p;mfg_alias_capacity=capacity;
  }mfg_alias_count++;
 }
 struct mfg_model_cookie cookie={++mfg_alias_serial,i,0};
 mfg_aliases_owner[i]=(struct mfg_model_alias){*out,NULL,(UINT)rd->Width,0,cookie.serial};
 HR(ID3D12Resource_SetPrivateData((ID3D12Resource*)*out,&mfg_model_cookie_guid,sizeof(cookie),&cookie));
 if(model_allocations_open){const UINT sizes[]={451584,36864,2304,4608,18432,73728,9216};mfg_initial_count++;for(UINT j=0;j<7;j++)if(rd->Width==sizes[j])mfg_initial_counts[j]++;}
 ReleaseSRWLockExclusive(&model_lock);return hr;
}
static void STDMETHODCALLTYPE mfg_pool_copy(ID3D12GraphicsCommandList*l,ID3D12Resource*dst,UINT64 doffset,ID3D12Resource*src,UINT64 soffset,UINT64 size){
 AcquireSRWLockExclusive(&mfg_pool_lock);AcquireSRWLockExclusive(&model_lock);
 struct mfg_model_alias*a=mfg_model_alias_find(dst);
 if(!a){ReleaseSRWLockExclusive(&model_lock);ReleaseSRWLockExclusive(&mfg_pool_lock);model_copy_hook(l,dst,doffset,src,soffset,size);return;}
 if(a->initialized||doffset||soffset||size!=a->bytes)model_fail("pooled model rewrite or partial upload");UINT alias_index=(UINT)(a-mfg_aliases_owner),bytes=a->bytes;UINT64 serial=a->serial;
 D3D12_HEAP_PROPERTIES hp;D3D12_HEAP_FLAGS flags;HR(ID3D12Resource_GetHeapProperties(src,&hp,&flags));D3D12_RESOURCE_DESC rd=ID3D12Resource_GetDesc(src);
 if(hp.Type!=D3D12_HEAP_TYPE_UPLOAD||rd.Dimension!=D3D12_RESOURCE_DIMENSION_BUFFER||rd.Width!=bytes)model_fail("pooled model source layout");
 void*source;unsigned char*raw=malloc(bytes);if(!raw)model_fail("pooled model snapshot allocation");D3D12_RANGE read={0,bytes},none={0,0};HR(ID3D12Resource_Map(src,0,&read,&source));memcpy(raw,source,bytes);ID3D12Resource_Unmap(src,0,&none);uint64_t digest=hash(raw,bytes);
 struct model_record*m=NULL;
 for(UINT i=0;i<model_count;i++)if(models[i].bytes==bytes&&models[i].initialized&&mfg_pool_hashes[i]==digest){
  void*previous;HR(ID3D12Resource_Map(models[i].upload,0,&read,&previous));int equal=!memcmp(raw,previous,bytes);ID3D12Resource_Unmap(models[i].upload,0,&none);if(equal){m=&models[i];mfg_pool_hits++;break;}
 }
 UINT fresh=!m;
 if(fresh){
  if(model_count==MODEL_CAPACITY)model_fail("distinct model pool capacity");m=&models[model_count];m->preparing=1;mfg_pool_hashes[model_count++]=digest;
  m->bytes=bytes;m->expanded=model_base_expanded(bytes);if(bytes==MODEL_BYTES||bytes==36864)m->expanded+=model_winograd_size(bytes);m->expanded+=model_enc16_size(bytes);
  D3D12_RESOURCE_DESC desc=ID3D12Resource_GetDesc(dst);desc.Width=m->expanded;desc.Alignment=0;D3D12_HEAP_PROPERTIES props={.Type=D3D12_HEAP_TYPE_DEFAULT};
  HR(model_committed_original(model_device,&props,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,NULL,&IID_ID3D12Resource,(void**)&m->r));m->va=ID3D12Resource_GetGPUVirtualAddress(m->r);
 }
 ReleaseSRWLockExclusive(&model_lock);
 if(fresh){
  /* The generic preparation consumes our private snapshot, never a second read
   * of caller memory. Its temporary source is never referenced by GPU commands. */
  ID3D12Resource*temporary=buffer(model_device,bytes,D3D12_HEAP_TYPE_UPLOAD);void*p;HR(ID3D12Resource_Map(temporary,0,&none,&p));memcpy(p,raw,bytes);D3D12_RANGE written={0,bytes};ID3D12Resource_Unmap(temporary,0,&written);
  transition(l,m->r,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST);
  model_copy_hook(l,m->r,0,temporary,0,bytes);
  transition(l,m->r,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);ID3D12Resource_Release(temporary);
 }
 free(raw);AcquireSRWLockExclusive(&model_lock);a=&mfg_aliases_owner[alias_index];if(a->r!=dst||a->serial!=serial)model_fail("model alias changed during upload");a->model=m;a->initialized=1;m->preparing=0;
 /* Keep the native allocation's prefix correct for the SDK's original ABI. */
 model_copy_original(l,dst,0,m->upload,0,bytes);ReleaseSRWLockExclusive(&model_lock);ReleaseSRWLockExclusive(&mfg_pool_lock);
}
static void mfg_pool_release(void){free(mfg_aliases_owner);mfg_aliases_owner=NULL;mfg_alias_count=mfg_alias_capacity=mfg_initial_count=0;memset(mfg_initial_counts,0,sizeof(mfg_initial_counts));memset(mfg_pool_hashes,0,sizeof(mfg_pool_hashes));mfg_pool_hits=0;}
