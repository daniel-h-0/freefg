/* SPDX-License-Identifier: MIT
 * Weak SDK-resource identities; descriptors refer to stable canonical models.
 * A private-data cookie prevents a recycled COM address from matching an alias.
 */
static const GUID mfg_model_cookie_guid={0xa3674db2,0x0d7a,0x4969,{0xb2,0x94,0x2e,0xf1,0x54,0x9d,0xa7,0x83}};
struct mfg_model_cookie{UINT64 serial;UINT index,pad;};
struct mfg_model_alias{ID3D12Resource*r;struct model_record*model;UINT bytes,initialized;UINT64 serial;};
static struct mfg_model_alias*mfg_aliases_owner;
static UINT mfg_alias_count,mfg_alias_capacity,mfg_initial_count,mfg_initial_counts[7];
static UINT64 mfg_alias_serial,mfg_pool_hashes[MODEL_CAPACITY],mfg_pool_hits;
static SRWLOCK mfg_pool_lock=SRWLOCK_INIT;
static struct mfg_model_alias*mfg_model_alias_find(ID3D12Resource*r){
 if(!r)return NULL;struct mfg_model_cookie cookie;UINT bytes=sizeof(cookie);
 if(FAILED(ID3D12Resource_GetPrivateData(r,&mfg_model_cookie_guid,&bytes,&cookie))||bytes!=sizeof(cookie)||cookie.index>=mfg_alias_count)return NULL;
 struct mfg_model_alias*a=&mfg_aliases_owner[cookie.index];
 return a->r==r&&a->serial==cookie.serial?a:NULL;
}
