/* SPDX-License-Identifier: MIT
 * Remove weak CPU tracking for SDK-released forwarding objects. The caller
 * holds fast_record_lock; actual resources retain their ordinary COM owners.
 */
static UINT64 mfg_retired_lists,mfg_retired_queues;
static void mfg_retire_scoped(struct scoped_com*p){
 if(p->kind==SCOPED_QUEUE){mfg_retired_queues++;return;}
 if(p->kind!=SCOPED_LIST)model_fail("unexpected scoped retirement kind");
 ID3D12GraphicsCommandList*l=(void*)p;
 AcquireSRWLockExclusive(&model_lock);
 for(UINT i=0;i<model_list_count;)if(model_lists[i].l==l){model_lists[i]=model_lists[--model_list_count];memset(&model_lists[model_list_count],0,sizeof(*model_lists));}else i++;
 ReleaseSRWLockExclusive(&model_lock);
 AcquireSRWLockExclusive(&flow_lock);
 for(UINT i=0;i<flow_list_count;)if(flow_lists[i].l==l){
  UINT last=--flow_list_count;flow_lists[i]=flow_lists[last];mfg_native_graph[i]=mfg_native_graph[last];mfg_graph_factor[i]=mfg_graph_factor[last];
  memset(&flow_lists[last],0,sizeof(*flow_lists));mfg_native_graph[last]=mfg_graph_factor[last]=0;
 }else i++;
 ReleaseSRWLockExclusive(&flow_lock);
 AcquireSRWLockExclusive(&frame_lock);
 for(UINT i=0;i<frame_list_count;)if(frame_lists[i].l==l){frame_lists[i]=frame_lists[--frame_list_count];memset(&frame_lists[frame_list_count],0,sizeof(*frame_lists));}else i++;
 ReleaseSRWLockExclusive(&frame_lock);
 AcquireSRWLockExclusive(&graph_lock);
 for(UINT i=0;i<graph_list_count;)if(graph_lists[i]==l){graph_lists[i]=graph_lists[--graph_list_count];graph_lists[graph_list_count]=NULL;}else i++;
 ReleaseSRWLockExclusive(&graph_lock);
 for(UINT i=0;i<nbinding;)if(bindings[i].l==l){bindings[i]=bindings[--nbinding];memset(&bindings[nbinding],0,sizeof(*bindings));}else i++;
 AcquireSRWLockExclusive(&span_lock);
 for(UINT i=0;i<nspans;)if(spans[i].list==l){if(spans[i].open)model_fail("retiring open timing span");spans[i]=spans[--nspans];memset(&spans[nspans],0,sizeof(*spans));}else i++;
 ReleaseSRWLockExclusive(&span_lock);mfg_retired_lists++;
}
