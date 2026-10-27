/* SPDX-License-Identifier: MIT
 * A private-data interface follows the native descriptor heap's lifetime.
 * It owns no heap reference, so there is no cycle or artificial GPU retention.
 * Both registration and destruction hold frame_lock then model_lock. A new
 * allocation supersedes an overlapping retired range before publishing slots;
 * a delayed old notifier can therefore never erase the new heap's records.
 */
static const GUID mfg_heap_note_guid={0x2ecc48ed,0xcbc0,0x428c,{0x97,0x08,0x80,0x5a,0x9a,0xee,0x75,0x42}};
struct mfg_heap_note{IUnknown iface;LONG refs;ID3D12DescriptorHeap*heap;SIZE_T cpu,bytes;UINT armed;
};
static struct mfg_heap_note**mfg_live_heaps;
static UINT mfg_live_heap_count,mfg_live_heap_capacity;
static UINT64 mfg_retired_heaps;
static void mfg_purge_heap_locked(struct mfg_heap_note*note){
 scale_purge_descriptors(note->cpu,note->bytes);
 for(UINT i=0;i<frame_desc_count;)if(frame_descs[i].cpu>=note->cpu&&frame_descs[i].cpu-note->cpu<note->bytes){frame_descs[i]=frame_descs[--frame_desc_count];memset(&frame_descs[frame_desc_count],0,sizeof(*frame_descs));}else i++;
 for(UINT i=0;i<model_descriptor_count;)if(model_descriptors[i].cpu>=note->cpu&&model_descriptors[i].cpu-note->cpu<note->bytes){model_descriptors[i]=model_descriptors[--model_descriptor_count];memset(&model_descriptors[model_descriptor_count],0,sizeof(*model_descriptors));}else i++;
 for(UINT i=0;i<model_heap_count;)if(model_heaps[i].h==note->heap){model_heaps[i]=model_heaps[--model_heap_count];memset(&model_heaps[model_heap_count],0,sizeof(*model_heaps));}else i++;
}
static ULONG STDMETHODCALLTYPE mfg_heap_note_addref(IUnknown*object){return (ULONG)InterlockedIncrement(&((struct mfg_heap_note*)object)->refs);}
static HRESULT STDMETHODCALLTYPE mfg_heap_note_query(IUnknown*object,REFIID iid,void**out){if(!out)return E_POINTER;*out=NULL;if(!IsEqualGUID(iid,&IID_IUnknown))return E_NOINTERFACE;*out=object;mfg_heap_note_addref(object);return S_OK;}
static ULONG STDMETHODCALLTYPE mfg_heap_note_release(IUnknown*object){
 struct mfg_heap_note*note=(void*)object;LONG refs=InterlockedDecrement(&note->refs);if(refs)return (ULONG)refs;
 if(note->armed){AcquireSRWLockExclusive(&frame_lock);AcquireSRWLockExclusive(&model_lock);
  for(UINT i=0;i<mfg_live_heap_count;i++)if(mfg_live_heaps[i]==note){mfg_purge_heap_locked(note);mfg_live_heaps[i]=mfg_live_heaps[--mfg_live_heap_count];mfg_retired_heaps++;break;}
  ReleaseSRWLockExclusive(&model_lock);ReleaseSRWLockExclusive(&frame_lock);
 }
 free(note);return 0;
}
static IUnknownVtbl mfg_heap_note_vtable={mfg_heap_note_query,mfg_heap_note_addref,mfg_heap_note_release};
static void mfg_watch_descriptor_heap(ID3D12Device*d,ID3D12DescriptorHeap*h,const D3D12_DESCRIPTOR_HEAP_DESC*desc){
 struct mfg_heap_note*note=calloc(1,sizeof(*note));if(!note)model_fail("heap lifetime note allocation");
 note->iface.lpVtbl=&mfg_heap_note_vtable;note->refs=1;note->heap=h;
 note->cpu=ID3D12DescriptorHeap_GetCPUDescriptorHandleForHeapStart(h).ptr;
 UINT stride=ID3D12Device_GetDescriptorHandleIncrementSize(d,desc->Type);
 if(!stride||desc->NumDescriptors>SIZE_MAX/stride)model_fail("heap descriptor range overflow");note->bytes=(SIZE_T)desc->NumDescriptors*stride;
 if(note->bytes>SIZE_MAX-note->cpu)model_fail("heap descriptor address overflow");
 HR(ID3D12DescriptorHeap_SetPrivateDataInterface(h,&mfg_heap_note_guid,&note->iface));
 AcquireSRWLockExclusive(&frame_lock);AcquireSRWLockExclusive(&model_lock);
 for(UINT i=0;i<mfg_live_heap_count;){struct mfg_heap_note*old=mfg_live_heaps[i];
  if(note->cpu<old->cpu+old->bytes&&old->cpu<note->cpu+note->bytes){mfg_purge_heap_locked(old);mfg_live_heaps[i]=mfg_live_heaps[--mfg_live_heap_count];}
  else i++;
 }
 if(mfg_live_heap_count==mfg_live_heap_capacity){UINT n=mfg_live_heap_capacity?mfg_live_heap_capacity*2:32;if(n<mfg_live_heap_capacity)model_fail("heap lifetime table overflow");void*p=realloc(mfg_live_heaps,(size_t)n*sizeof(*mfg_live_heaps));if(!p)model_fail("heap lifetime table allocation");mfg_live_heaps=p;mfg_live_heap_capacity=n;}
 mfg_live_heaps[mfg_live_heap_count++]=note;note->armed=1;
 if(desc->Flags&D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE){
  if(model_heap_count==128)model_fail("live heap tracking capacity");UINT i=model_heap_count++;
  model_heaps[i].h=h;model_heaps[i].cpu=note->cpu;model_heaps[i].gpu=ID3D12DescriptorHeap_GetGPUDescriptorHandleForHeapStart(h).ptr;
  model_heaps[i].count=desc->NumDescriptors;model_heaps[i].stride=stride;
 }
 ReleaseSRWLockExclusive(&model_lock);ReleaseSRWLockExclusive(&frame_lock);
 mfg_heap_note_release(&note->iface);
}
