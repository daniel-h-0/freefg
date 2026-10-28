/* SPDX-License-Identifier: MIT
 * Colour-history cache bookkeeping, shared with the CPU lifecycle fixture.
 * Callers serialize these helpers with scale_lock. GPU ordering and ownership
 * remain the responsibility of the existing single-queue submission path.
 */
#ifndef FREEFG_FRAME_SCALE_HISTORY_H
#define FREEFG_FRAME_SCALE_HISTORY_H
struct scale_view {
 UINT kind;ID3D12Resource*r,*counter;
 union {D3D12_SHADER_RESOURCE_VIEW_DESC srv;D3D12_UNORDERED_ACCESS_VIEW_DESC uav;D3D12_CONSTANT_BUFFER_VIEW_DESC cbv;} d;
};
struct scale_image {
 struct scale_view source;ID3D12Resource*low;UINT w,h,refs;
 ID3D12GraphicsCommandList*sampled_list;UINT64 sampled_graph;
 UINT copy_preserved,low_valid,low_pending;
 struct scale_image*next;
};

/* NULL is an aliasing wildcard: every cached source may have changed. */
static void scale_history_written(struct scale_image*head,ID3D12Resource*r){
 for(struct scale_image*i=head;i;i=i->next)if(!r||i->source.r==r){
  i->sampled_graph=0;
  i->copy_preserved=i->low_valid=i->low_pending=0;
 }
}
static void scale_history_reset(struct scale_image*head,ID3D12GraphicsCommandList*l){
 for(struct scale_image*i=head;i;i=i->next)if(i->sampled_list==l){
  i->sampled_graph=0;
  /* Resetting a list before submission abandons its recorded reduction. */
  if(i->low_pending)i->low_valid=0;
  i->low_pending=0;
 }
}
static void scale_history_copied(struct scale_image*head,ID3D12Resource*r){
 for(struct scale_image*i=head;i;i=i->next)if(i->source.r==r)i->copy_preserved=1;
}
static int scale_history_reusable(const struct scale_image*i,ID3D12GraphicsCommandList*l){
 return i->copy_preserved&&i->low_valid&&(!i->low_pending||i->sampled_list==l);
}
static void scale_history_submitted(struct scale_image*head,ID3D12CommandList*l){
 for(struct scale_image*i=head;i;i=i->next)if((ID3D12CommandList*)i->sampled_list==l)i->low_pending=0;
}
#endif
