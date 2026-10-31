/* SPDX-License-Identifier: MIT
 * Aspect-preserving generated-frame cap across native 2x and MFG 3x/4x.
 * Original engine depth/MV resources and SDK allocations remain intact.
 */
#include "mfg_frame_contract.h"
#include "mfg_geometry_math.h"
static UINT mfg_second_phase_pending,mfg_active_factor;
static UINT mfg_native_graph[128],mfg_graph_factor[128];
static UINT mfg_profile_checked,mfg_profile_general;
static UINT mfg_output_w,mfg_output_h,mfg_cap_w,mfg_cap_h;
static UINT mfg_scale_actual[128],mfg_scale_frame_actual,mfg_native_repeat_ready;
static int mfg_cap_reject(UINT li,const char*why){
 if(!mfg_scale_actual[li]){
  scale_block(why);flow_lists[li].active=0;flow_lists[li].step=FLOW_END;mfg_second_phase_pending=0;return 1;
 }
 model_fail(why);return 1;
}
static int mfg_geometry_shader(uint64_t actual,uint64_t expected,UINT step){
 if(actual==expected)return 1;
 if(step==1&&actual==0xe1b6404f97c97c6bULL)return 1;
 if(step>=28&&(step-28)%16==15&&actual==0x7da098e8e69a54f8ULL)return 1;
 /* 2x warp permutations (one per frame, stage 30). HDR10: 276a73a0 (engine motion vectors) and 0044a8b4 (pixel motion
  * vectors), siblings of SDR 8809b169 and f9c94458. */
 if(step==30&&(actual==0x3a7d9dfa831ba4f3ULL||actual==0x8809b169edee2ba8ULL||actual==0xf440a4f4a7311d91ULL||actual==0xf9c944580da4662dULL||actual==0x276a73a0ff428af4ULL||actual==0x0044a8b41303a9f7ULL))return 1;
 if(step==30&&actual==0xd8e6c564b3ae9acfULL)return 1;
 /* 3x/4x HDR10 warps, one per generated frame (stages 30/46/62): fda36bb6 (engine motion vectors) and c3824a65 (pixel
  * motion vectors), siblings of SDR e3914510 and 72d9e71a. */
 if(step>=28&&(step-28)%16==2&&(actual==0xfda36bb6a452bbc1ULL||actual==0xc3824a65b3d90388ULL))return 1;
 /* Pixel-space MV scatter has the same resource/constant layout. This stage
  * keeps the engine input grid, constants and dispatch unchanged. */
 if(step>=28&&(step-28)%16==0&&actual==0xa80597e7d1e80741ULL)return 1;
 if(step>=28&&(step-28)%16==2&&actual==0x72d9e71a91664cccULL)return 1;
 if(step==28&&(actual==0x437542192dd795c8ULL||actual==0x995b75ef9d54204aULL||actual==0x8c09ff6372805dbfULL))return 1;
 return 0;
}
static int mfg_cap_dispatch_locked(ID3D12GraphicsCommandList*l,uint64_t shader,UINT*x,UINT*y,UINT*z){
 UINT li=flow_slot(l),step=flow_lists[li].step;
 if(shader==0xbc7a0d422d51c159ULL){
  mfg_native_graph[li]=0;mfg_graph_factor[li]=3;
  if(mfg_second_phase_pending)model_fail("missing MFG phase");
  if(flow_lists[li].active&&step!=FLOW_END)model_fail("incomplete 2x/3x/4x graph");
  mfg_scale_actual[li]=mfg_scale_frame_actual=mfg_native_repeat_ready=0;
  UINT*c=flow_lists[li].values[3];if((flow_lists[li].mask[3]&1023)!=1023)return mfg_cap_reject(li,"MFG preprocess constants missing");
  UINT requested_w,requested_h;
  if(!c[2]||!c[3]){flow_lists[li].active=0;flow_lists[li].step=FLOW_END;return 1;}
  if(!bc250_fg_dimensions(&mfg_settings_applied,c[2],c[3],&requested_w,&requested_h))model_fail("invalid configured FG geometry");
  mfg_settings_note_size(c[2],c[3]);
  if(requested_w==c[2]&&requested_h==c[3]){
   scale_report_full(c[2],c[3]);
   flow_lists[li].active=0;flow_lists[li].step=FLOW_END;return 1;
  }
  if(!mfg_profile_checked){
   char path[1500];snprintf(path,sizeof(path),
 "%s\\freefg-scaling.required",
 patchdir);FILE*f=profile_fopen(path,"r");
   if(f){mfg_profile_general=fgetc(f)=='1';fclose(f);}mfg_profile_checked=1;
  }
  /* Archived fixed-ratio profiles remain valid for old 1440p comparisons only. */
  if(!mfg_profile_general&&(c[2]!=2560||c[3]!=1440))model_fail("general cap requires its matching resampling profile");
  if(c[0]||c[1]||c[4]||c[5]||c[2]!=c[6]||c[3]!=c[7]){
   /* A colour sub-rectangle is not a qualified scaled layout: generate this frame at output resolution instead. */
   static LONG logged;if(!InterlockedExchange(&logged,1))logline("FRAME_CAP colour sub-rectangle: generating at output resolution\n");
   flow_lists[li].active=0;flow_lists[li].step=FLOW_END;return 1;
  }
  if(mfg_output_w!=c[2]||mfg_output_h!=c[3]){
   mfg_output_w=c[2];mfg_output_h=c[3];
   mfg_cap_w=requested_w;mfg_cap_h=requested_h;
   char line[160];snprintf(line,sizeof(line),"MFG_CAP output=%ux%u synthesis=%ux%u\n",mfg_output_w,mfg_output_h,mfg_cap_w,mfg_cap_h);logline(line);
  }
  UINT mode=scale_begin_graph(l);
  if(!mode){flow_lists[li].active=0;flow_lists[li].step=FLOW_END;return 1;}
  mfg_scale_actual[li]=mfg_scale_frame_actual=mode==2;
  if(mfg_scale_actual[li])mfg_settings_note_generated(mfg_cap_w,mfg_cap_h);
  step=0;flow_lists[li].active=1;
 }
 if((shader==0x3ec94c97ef9046bcULL||shader==0xa80597e7d1e80741ULL)&&mfg_second_phase_pending){step=mfg_second_phase_pending;flow_lists[li].active=1;mfg_native_graph[li]=0;
 mfg_scale_actual[li]=mfg_scale_frame_actual;
 }
 /* MFG Unlocker's default model repeats the native network for each temporal
  * phase. Only the shared colour preprocessing is omitted after phase one. */
 if(shader==0x9a31ac9b7e42f797ULL&&mfg_native_repeat_ready){
  step=1;flow_lists[li].active=1;mfg_native_graph[li]=1;
  mfg_scale_actual[li]=mfg_scale_frame_actual;mfg_native_repeat_ready=0;
 }
 if(!flow_lists[li].active)return 1;
 if(step==FLOW_END){flow_lists[li].active=0;return 1;}
 if(step==1&&shader==0x9a31ac9b7e42f797ULL)mfg_native_graph[li]=1;
 UINT native=mfg_native_graph[li],stage=native?mg_native_stage(step):step;
 if(!native&&step==2){
  if((flow_lists[li].mask[2]&4095)!=4095)return mfg_cap_reject(li,"MFG flow constants missing");
  UINT maximum=flow_lists[li].values[2][11];
  if(maximum==31)mfg_graph_factor[li]=4;else if(maximum==42)mfg_graph_factor[li]=3;else return mfg_cap_reject(li,"unknown MFG flow factor");
 }
 if(step==44||step==60)mfg_graph_factor[li]=mfg_active_factor;
 if(step==28&&!native)mfg_active_factor=mfg_graph_factor[li];
 UINT factor=native?2:mfg_graph_factor[li];
 const struct mfg_frame_row*rows=factor==4?mfg_frame_rows4:mfg_frame_rows;
 const struct mfg_frame_row*row=&rows[stage];
 UINT index=row->index,n=row->n;uint64_t expected=row->shader;
 if(native&&step<23){index=flow_rows[step].index;n=flow_rows[step].n;expected=flow_rows[step].shader;}
 if(!mfg_geometry_shader(shader,expected,stage)){
  char line[160];snprintf(line,sizeof(line),"MFG_CAP mismatch factor=%u step=%u actual=%016llx expected=%016llx\n",factor,step,(unsigned long long)shader,(unsigned long long)expected);logline(line);return mfg_cap_reject(li,"MFG graph changed");
 }
 UINT c[64],original[64],groups[3]={*x,*y,*z};
 if((flow_lists[li].mask[index]&((1ULL<<n)-1))!=((1ULL<<n)-1))return mfg_cap_reject(li,"MFG root constants missing");
 memcpy(c,flow_lists[li].values[index],n*4);memcpy(original,c,n*4);
 uint64_t mask=mg_geometry(mfg_output_w,mfg_output_h,stage,!native,c,groups);
 for(UINT j=0;j<n;j++)if((mask&(1ULL<<j))&&c[j]!=original[j]){
  char line[160];snprintf(line,sizeof(line),"MFG_GEOMETRY step=%u word=%u actual=%08x expected=%08x\n",step,j,original[j],c[j]);logline(line);return mfg_cap_reject(li,"MFG source geometry differs");
 }
 if(!mfg_scale_actual[li]){
  if((stage==0||stage>=28&&((stage-28)%16==2||(stage-28)%16==15))&&!scale_check_bindings(l,shader))return mfg_cap_reject(li,"unsupported SDK resource layout");
  /* Observe the complete original graph. Do not rewrite any constants, groups or descriptors. */
  goto mfg_geometry_done;
 }
 /* The reduced network keeps all five virtual levels, even at one pixel.
  * Reusing the SDK's tiny-image level merging could enlarge a middle layer
  * during reduction (for example 1x5 -> 1x4) beyond its original allocation. */
 mg_geometry(mfg_cap_w,mfg_cap_h,stage,(!native)|MG_UNET_CANONICAL,c,groups);
 if(stage>=28&&(stage-28)%16==1){
  for(UINT j=0;j<2;j++){
   UINT source=j?mfg_output_h:mfg_output_w,target=j?mfg_cap_h:mfg_cap_w;
   float value;memcpy(&value,original+2+j,4);
   value*=((float)mg_ceil(target,16)*16/target)/((float)mg_ceil(source,16)*16/source);
   mg_float(c+2+j,value);
  }
 }
 if(stage>=28&&(stage-28)%16==2){
  for(UINT j=0;j<2;j++){float value;memcpy(&value,original+26+j,4);value*=(float)(j?mfg_cap_h:mfg_cap_w)/(j?mfg_output_h:mfg_output_w);mg_float(c+26+j,value);}
 }

 if(stage>=31&&(stage-28)%16>=3&&(stage-28)%16<=14){
  UINT k=(stage-28)%16-3,old_half[2],new_half[2];
  if(k==5||k==7||k==9||k==11){
   mg_unet_dimensions(mfg_output_w,mfg_output_h,k-1,!native,old_half);
   mg_unet_dimensions(mfg_cap_w,mfg_cap_h,k-1,(!native)|MG_UNET_CANONICAL,new_half);
  }else for(UINT j=0;j<2;j++){old_half[j]=mg_ceil(original[j],2);new_half[j]=mg_ceil(c[j],2);}
  for(UINT j=0;j<2;j++){
   if(original[j]<c[j]||original[j]-c[j]>65535||old_half[j]<new_half[j]||old_half[j]-new_half[j]>65535)model_fail("scaled texture extent exceeds its allocation");
   c[2+j]=(original[j]-c[j])|((old_half[j]-new_half[j])<<16);
  }
 }
 memcpy(flow_lists[li].scaled[index],c,n*4);
 flow_constants_original(l,index,n,c,0);*x=groups[0];*y=groups[1];*z=groups[2];
mfg_geometry_done:
 flow_lists[li].step=step+1;
 if(step==(native?22:27))flow_frames++;
 if(native&&step==37){flow_lists[li].step=FLOW_END;
  mfg_native_repeat_ready=1;
 }
 if(!native&&(step==43||step==59||step==75)){
  UINT end=28+16*(factor-1);mfg_second_phase_pending=step+1<end?step+1:0;
  if(!mfg_second_phase_pending)flow_lists[li].step=FLOW_END;
 }
 if(flow_lists[li].step==FLOW_END&&!mfg_scale_actual[li])scale_observation_done();
 return 1;
}
