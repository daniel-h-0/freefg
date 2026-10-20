/* SPDX-License-Identifier: MIT
 * Reuse identical SDK compute PSOs across factor changes. The existing PSO
 * tracking owns the retained reference; each cache hit AddRefs for its SDK caller.
 */
static struct{ID3D12PipelineState*p;ID3D12RootSignature*root;void*code;SIZE_T size;UINT node,flags;uint64_t hash;}mfg_pipelines[256];
static UINT mfg_pipeline_count;static UINT64 mfg_pipeline_hits;
static HRESULT mfg_cached_compute(ID3D12Device*d,const D3D12_COMPUTE_PIPELINE_STATE_DESC*desc,REFIID iid,void**out){
 uint64_t digest=hash(desc->CS.pShaderBytecode,desc->CS.BytecodeLength);
 if(IsEqualGUID(iid,&IID_ID3D12PipelineState))for(UINT i=0;i<mfg_pipeline_count;i++){
  __typeof__(*mfg_pipelines)*c=&mfg_pipelines[i];
  if(c->root==desc->pRootSignature&&c->node==desc->NodeMask&&c->flags==desc->Flags&&c->size==desc->CS.BytecodeLength&&c->hash==digest&&!memcmp(c->code,desc->CS.pShaderBytecode,c->size)){
   ID3D12PipelineState_AddRef(c->p);*out=c->p;mfg_pipeline_hits++;return S_OK;
  }
 }
 HRESULT hr=compute_hook(d,desc,iid,out);
 if(SUCCEEDED(hr)){
  ID3D12PipelineState_AddRef((ID3D12PipelineState*)*out);
  if(IsEqualGUID(iid,&IID_ID3D12PipelineState)){
   if(mfg_pipeline_count==256)model_fail("distinct PSO cache capacity");__typeof__(*mfg_pipelines)*c=&mfg_pipelines[mfg_pipeline_count++];
   c->code=malloc(desc->CS.BytecodeLength);if(!c->code)model_fail("PSO cache allocation");memcpy(c->code,desc->CS.pShaderBytecode,desc->CS.BytecodeLength);c->size=desc->CS.BytecodeLength;c->hash=digest;c->root=desc->pRootSignature;c->node=desc->NodeMask;c->flags=desc->Flags;c->p=*out;
  }
 }return hr;
}
static void mfg_release_pipeline_cache(void){for(UINT i=0;i<mfg_pipeline_count;i++)free(mfg_pipelines[i].code);memset(mfg_pipelines,0,sizeof(mfg_pipelines));mfg_pipeline_count=0;mfg_pipeline_hits=0;}
