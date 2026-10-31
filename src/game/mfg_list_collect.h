/* SPDX-License-Identifier: MIT
 * The per-list tables (bindings, and the model, flow, frame, graph and scaling lists: 128 each) drop the lists the runtime
 * has released at a frame-count change; a session that only resizes, toggles HDR or otherwise recreates its lists filled
 * them and ended the game. So the first pipeline bound on a new list past three quarters of any of them retires the
 * runtime's idle lists first (those only this proxy still references), as a frame-count change does. Caller holds
 * fast_record_lock. */
static void fast_collect_lists(ID3D12GraphicsCommandList*l){
 UINT most=nbinding;const UINT counts[]={model_list_count,flow_list_count,frame_list_count,graph_list_count,scale_list_count};
 for(UINT i=0;i<sizeof(counts)/sizeof(*counts);i++)if(counts[i]>most)most=counts[i];
 if(most<XEFG_PROBE_BINDINGS*3/4||!fast_scope)return;
 for(UINT b=0;b<nbinding;b++)if(bindings[b].l==l)return;  /* a known list adds no entry */
 scoped_collect_idle(fast_scope);
 char line[200];snprintf(line,sizeof(line),"MFG_TRACKING idle lists retired at %u tracked lists: %u bindings left of %u\n",most,nbinding,(UINT)XEFG_PROBE_BINDINGS);
 proxy_log(line);
}
