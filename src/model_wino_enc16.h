/* SPDX-License-Identifier: MIT
 * Exact Winograd F(2x2,3x3) coefficients for the conv+pool reconstruction encoders
 * 1a3b0782583fef19 (2304-byte model, 16->16), f030948d38e74671 (4608, 16->32) and
 * e83e868f8d5d2c0f (18432, 32->64). A segment is appended after the existing
 * byte+float layout of every model of a selected size, so the original ABI and the
 * float kernels are untouched:
 *   [0,B) raw int8 | [B,5B) float(int8) | U[chunk][half][cin][p][k] float | zero float4
 * (chunk = raw 2304-byte chunk = output slice * input slices + input slice, so the segment
 * does not depend on how a layer splits its channels)
 * Raw layout of the SDK buffer: 2304-byte chunk (slice*CS+in slice), inside
 * tap*256 + (cin/4)*64 + cout*4 + cin%4. U = G' g G'^T with G' = 2G (|U| <= 1152).
 * Profile marker wino-enc16.required holds a size mask: 1 = 2304 (S1,CS1), 2 = 4608 (S2,CS1),
 * 4 = 18432 (S4,CS2), 8 = 9216 (S2,CS2), 16 = 73728 (S8,CS4), 32 = 36864 (S4,CS4, after the
 * flow-graph segment). Unused models of a selected
 * size (other layers) get a harmless unread segment.
 * Mask bit 128: a third, conv64-layout segment for 36864-byte models (the fused flow refinement kernel
 * wino_ref64 for 558c3931/08155f47/990b9bf8/44702172), after the enc16 segment (bit 32 required):
 * U[chunk = out slice*4 + in slice][half][cin][p][k8] from raw[chunk*2304 + (cout/4)*576 + tap*64 +
 * (cin/4)*16 + (cout%4)*4 + cin%4] (cout, cin local to their 16-channel slices), then a zero float4.
 * Mask bit 1024: FP16 copies of the 2D segments (enc16, then the conv64 refinement segment of 36864-byte
 * models), appended after every FP32 segment so no earlier offset moves: [enc16: chunks*8192][ref64: 16*8192].
 * Every U is an integer |U| <= 1152, exact in FP16; kernels read them as SGPR halves through v_fma_mix, which
 * halves their scalar coefficient traffic.
 * Mask bit 256: whole-sum proofs for kernels that accumulate every input slice in FP32 and inverse-
 * transform once: for each multi-slice segment, model and (output channel, position), 512 * the sum over
 * all input channels of |U| must be <= 2^24 (|v| <= 512), or the owner fails closed.
 */
static UINT model_wino_enc16;
static UINT model_enc16_layout(UINT bytes,UINT*cin_slices){
 UINT bit=bytes==2304?1:bytes==4608?2:bytes==18432?4:bytes==9216?8:bytes==73728?16:bytes==36864?32:0;
 if(!(model_wino_enc16&bit))return 0;
 *cin_slices=bytes==18432||bytes==9216?2:bytes==73728||bytes==36864?4:1;return bytes/2304;
}
/* After the byte+float layout and, for owner7 36864-byte models, after the flow-graph
 * Winograd segment that model_winograd_pack writes there. */
static UINT model_enc16_offset(UINT bytes){return model_base_expanded(bytes)+(model_owner_enabled==7&&(bytes==MODEL_BYTES||bytes==36864)?model_winograd_size(bytes):0);}
/* Mask bit 64: a second, 1D F(2,3) segment for 2304/4608-byte models (60edebbb, b3ddf030), placed after
 * the 2D segment: U1[chunk][cin][row][j][16 couts] = G' g_row (rows 2g0 | g0+g1+g2 | g0-g1+g2 | 2g2). */
static UINT model_row16_size(UINT bytes){return (model_wino_enc16&64)&&((bytes==2304&&model_wino_enc16&1)||(bytes==4608&&model_wino_enc16&2))?bytes/2304*12288u:0;}
static UINT model_ref64_size(UINT bytes){return (model_wino_enc16&128)&&bytes==36864?16*16384u+16u:0;}
static UINT model_f16_size(UINT bytes){UINT cs;UINT chunks=model_enc16_layout(bytes,&cs);if(!(model_wino_enc16&1024)||!chunks)return 0;return chunks*8192u+(model_ref64_size(bytes)?16*8192u:0);}
static UINT model_enc16_size(UINT bytes){UINT cs;UINT chunks=model_enc16_layout(bytes,&cs);return (chunks?chunks*16384u+16u:0)+model_row16_size(bytes)+model_ref64_size(bytes)+model_f16_size(bytes);}
/* Exact for integers |v| < 2048 (all U: |U| <= 1152). */
static uint16_t model_half_int(int v){UINT mag=v<0?(UINT)-v:(UINT)v;if(!mag)return 0;if(mag>=2048)model_fail("FP16 Winograd coefficient range");UINT e=0;while((1u<<(e+1))<=mag)e++;return (uint16_t)((v<0?0x8000u:0)|((e+15)<<10)|((mag-(1u<<e))<<(10-e)));}
/* Every partial sum of a whole multi-slice FP32 accumulation is bounded by 512 * sum |U|. */
static void model_enc16_whole_sum(const float*seg,UINT slices,UINT cs,const char*what){
 for(UINT s=0;s<slices;s++)for(UINT h=0;h<2;h++)for(UINT p=0;p<16;p++)for(UINT k=0;k<8;k++){
  UINT64 sum=0;
  for(UINT is=0;is<cs;is++)for(UINT cin=0;cin<16;cin++){int u=(int)seg[((((s*cs+is)*2+h)*16+cin)*16+p)*8+k];sum+=(UINT64)(u<0?-u:u);}
  if(sum*512>16777216ull)model_fail(what);
 }
}
static void model_enc16_pack(const void*snapshot,UINT bytes,UINT expanded){
 UINT cs,chunks=model_enc16_layout(bytes,&cs);if(!chunks)return;
 if(expanded!=model_enc16_offset(bytes)+model_enc16_size(bytes))model_fail("enc16 Winograd segment size");
 static const int G2[4][3]={{2,0,0},{1,1,1},{1,-1,1},{0,0,2}};
 const int8_t*raw=snapshot;float*seg=(float*)((char*)snapshot+model_enc16_offset(bytes));
 (void)cs;
 for(UINT chunk=0;chunk<chunks;chunk++){
  for(UINT cout=0;cout<16;cout++)for(UINT cin=0;cin<16;cin++){
   int g[3][3];for(UINT ky=0;ky<3;ky++)for(UINT kx=0;kx<3;kx++)g[ky][kx]=raw[chunk*2304+(ky*3+kx)*256+(cin>>2)*64+cout*4+(cin&3)];
   for(UINT i=0;i<4;i++)for(UINT j=0;j<4;j++){
    int u=0;for(UINT a=0;a<3;a++)for(UINT b=0;b<3;b++)u+=G2[i][a]*g[a][b]*G2[j][b];
    if(u>1152||u<-1152)model_fail("enc16 Winograd coefficient bound");
    seg[(((chunk*2+(cout>>3))*16+cin)*16+i*4+j)*8+(cout&7)]=(float)u;
   }
  }
 }
 memset(seg+chunks*4096,0,16);
 if(model_row16_size(bytes)){
  float*row=seg+chunks*4096+4;
  for(UINT chunk=0;chunk<chunks;chunk++)for(UINT cin=0;cin<16;cin++)for(UINT r=0;r<3;r++)for(UINT cout=0;cout<16;cout++){
   int g[3];for(UINT kx=0;kx<3;kx++)g[kx]=raw[chunk*2304+(r*3+kx)*256+(cin>>2)*64+cout*4+(cin&3)];
   int u[4]={2*g[0],g[0]+g[1]+g[2],g[0]-g[1]+g[2],2*g[2]};
   for(UINT j=0;j<4;j++)row[(((chunk*16+cin)*3+r)*4+j)*16+cout]=(float)u[j];
  }
 }
 if(model_wino_enc16&256&&cs>1)model_enc16_whole_sum(seg,chunks/cs,cs,"enc16 whole-sum FP32 bound");
 if(model_ref64_size(bytes)){
  float*ref=seg+chunks*4096+4+model_row16_size(bytes)/4;
  for(UINT chunk=0;chunk<16;chunk++)for(UINT cout=0;cout<16;cout++)for(UINT cin=0;cin<16;cin++){
   int g[3][3];for(UINT ky=0;ky<3;ky++)for(UINT kx=0;kx<3;kx++)g[ky][kx]=raw[chunk*2304+(cout>>2)*576+(ky*3+kx)*64+(cin>>2)*16+(cout&3)*4+(cin&3)];
   for(UINT i=0;i<4;i++)for(UINT j=0;j<4;j++){
    int u=0;for(UINT a=0;a<3;a++)for(UINT b=0;b<3;b++)u+=G2[i][a]*g[a][b]*G2[j][b];
    if(u>1152||u<-1152)model_fail("refinement Winograd coefficient bound");
    ref[(((chunk*2+(cout>>3))*16+cin)*16+i*4+j)*8+(cout&7)]=(float)u;
   }
  }
  memset(ref+16*4096,0,16);
  if(model_wino_enc16&256)model_enc16_whole_sum(ref,4,4,"refinement whole-sum FP32 bound");
 }
 if(model_f16_size(bytes)){
  uint16_t*half=(uint16_t*)((char*)seg+chunks*16384u+16u+model_row16_size(bytes)+model_ref64_size(bytes));
  for(UINT i=0;i<chunks*4096;i++)half[i]=model_half_int((int)seg[i]);
  if(model_ref64_size(bytes)){const float*ref=seg+chunks*4096+4+model_row16_size(bytes)/4;for(UINT i=0;i<16*4096;i++)half[chunks*4096+i]=model_half_int((int)ref[i]);}
 }
}
static void model_enc16_configure(void){
 char path[1400];snprintf(path,sizeof(path),"%s\\wino-enc16.required",patchdir);
 FILE*f=*patchdir?fopen(path,"r"):NULL;
 if(!f)model_fail("enc16 Winograd build requires its profile marker");
 unsigned value;char extra;int fields=fscanf(f,"%u %c",&value,&extra);fclose(f);
 if(fields!=1||!value||value>2047||(value&64&&!(value&3))||(value&128&&!(value&32)))model_fail("invalid enc16 Winograd marker");
 if(model_owner_enabled!=7)model_fail("enc16 Winograd requires owner7");
 model_wino_enc16=value;char line[120];snprintf(line,sizeof(line),"WINO_ENC16 exact F(2x2,3x3) coefficients mask=%u\n",value);logline(line);
}
