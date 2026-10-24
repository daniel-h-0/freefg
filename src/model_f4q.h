/* SPDX-License-Identifier: MIT
 * F4Q (XEFG_F4Q, the multi-frame proxy since FreeFG 1.1): the model side of this project's FP32 Winograd F(4x4,3x3)
 * kernels, src/kernels/f4q_dec16.hlsl and f4q_enc16.hlsl, which replace this project's F(2x2) or 1D kernels of seven
 * U-Net pipelines (src/game/f4q.h chooses the pipelines and their dispatch geometry):
 *   F4Q (1.1.0)    the decoder b3941ac8 (both sizes, 2304-byte models) and the encoder f030948d (4608-byte models); since
 *                  1.1.2 the decoder fills and transforms in packed 16-bit arithmetic and both skip groups wholly below
 *                  the output (f4q_dec16.hlsl XU2D, TRIM): the same outputs as their 1.1.0 form for every input
 *   F4Q2 (1.1.2)   the encoders 1a3b0782 (16 -> 16, 2304-byte models: the segment F4Q writes), e83e868f (32 -> 64,
 *                  18432-byte models) and 9e0080ee (64 -> 128, 73728-byte models); their kernel keeps one FP32 channel
 *                  chain over all 32 / 64 input channels (f4q_enc16.hlsl CIN_SLICES)
 *   F4Q3 (1.1.2)   the row layers 60edebbb (16 -> 16, 2304-byte models) and b3ddf030 (32 -> 16, 4608-byte models), in
 *                  place of their 1D F(2,3) kernel (wino_row16.hlsl): signed, unpooled outputs, F4Q's segments, no new
 *                  one; it has no switch of its own
 * Their outputs matched the F(2x2) / 1D kernels' in every test (SDK test rows; in-game comparisons on native 2x and
 * OptiScaler 3x), but F(4x4) arithmetic rounds and no proof covers every input: identical in every test, not proven for
 * every input.
 *
 * The FP16 forms (FreeFG 1.1.2, on by default while F4Q is on; BC250_XEFG_EXACT=1 turns them off): faster forms of
 * seven U-Net kernels whose outputs differ slightly from the exact forms' (and so from Intel's), read from
 * <hash>.fp16.dxil (src/game/f4q.h). The forms' mask has four bits; this build turns on bits 1 and 2 (FP16_DEFAULT):
 *   1  the F4Q2 encoders read FP16 U'/2 coefficient pairs (f4q_enc16.hlsl HALF_TABLE): e83e868f and 9e0080ee from their F4Q2
 *      segment, written in place as FP16 (only those layers read it); 1a3b0782 from an FP16 copy of the 2304-byte
 *      models' segment (the FP32 table stays for b3941ac8 and 60edebbb, which read it too)
 *   2  packed-FP16 MACs (pk16.hlsli) in the F(2x2) kernels of 1f27b449, f2e2e13f, 5654aa38 and 4bb52a63, reading an FP16
 *      copy (U' x 2^-8) of the enc16 segment of 73728-, 18432-, 9216- and 36864-byte models
 * Bits 4 and 8 are not turned on by this build, and its package has no files for them: b3941ac8 and f030948d run their
 * F4Q kernels and the row layers 60edebbb and b3ddf030 F4Q3's. They describe forms the owner can lay out:
 *   4  b3941ac8 (both sizes) and f030948d read FP16 U'/2 pairs from an FP16 copy of the 2304- / 4608-byte models' segment
 *   8  packed-FP16 MACs in the 1D kernels of the row layers 60edebbb and b3ddf030 (wino_row16.hlsl PK16), reading an FP16
 *      copy of the row16 segment of 2304- / 4608-byte models; F4Q3 is then off for both layers
 * All bits need F4Q on (not its diagnostic); bit 1 applies to the F4Q2 layers that are on. The copies come after the
 * F4Q segment at fixed float4 indices, whatever is on (a room nothing reads is zeros): the PK copy (bits 2 and 8) at
 * fp16_pk_base, then for 2304- and 4608-byte models the half copy (bits 1 and 4) at fp16_half_base. A layout that does
 * not give these indices drops the bit (logged).
 *
 * Switches (read when a context is accelerated, f4q_configure):
 *   BC250_XEFG_F4Q=0 (also off, false, no)   F4Q off, and with it F4Q2, F4Q3 and the FP16 forms: the F(2x2) and 1D
 *                                            kernels run, as in 1.0.x (the U-Net as 1.1.1 with F4Q off)
 *   BC250_XEFG_F4Q=1 (also on, true, yes)    F4Q on, whatever settings.ini says
 *   otherwise                                BC250-XeFG/settings.ini [BC250] F4Q=0 turns it off; on by default
 *   BC250_XEFG_F4Q2=0 / =1 (same words)      F4Q2 off / on while F4Q is on, whatever settings.ini says
 *   otherwise                                settings.ini [BC250] F4Q2=0 turns it off (F4Q stays on); on by default
 *   BC250_XEFG_EXACT=1 / =0 (same words)     the FP16 forms off / on, whatever settings.ini says
 *   otherwise                                settings.ini [BC250] Exact=1 turns them off; on by default. Off, every
 *                                            kernel is in its exact form: F4Q, F4Q2 and F4Q3 run their F(4x4) kernels
 *                                            and the other U-Net layers their F(2x2) kernels
 *   BC250_XEFG_F4Q_SHADOW=1                  diagnostic, only while F4Q is on: the F(2x2) / 1D kernels keep the output and
 *                                            the F4Q, F4Q2 and F4Q3 kernels run beside them; this project's own GPU passes
 *                                            count equal and differing outputs (src/game/f4q.h; nothing of the content
 *                                            is read). The FP16 forms are off while it runs.
 * F4Q stays off when the model layout does not give the segment offsets of 2304- and 4608-byte models the kernels were
 * compiled for, and an F4Q2 layer of 18432- or 73728-byte models when its own offset differs (below).
 *
 * The segment, appended after the enc16 family's segments of 2304-, 4608-, 18432- and 73728-byte models
 * (src/model_wino_enc16.h), one 16->16 slice per 2304-byte chunk s (chunk = output slice * input slices + input slice;
 * raw layout tap * 256 + (cin / 4) * 64 + cout * 4 + cin % 4, as model_enc16_pack reads it), U' = G' g G'^T with
 * G' = 24 G, in FP32 (|U'| <= 128 * 24 * 24 = 73728 for every int8 g: exact):
 *   float4 index TBASE + (s * 6 + i) * 384 + (c * 6 + j) * 4 + q  = U'[i][j][c][4q .. 4q+3]
 * i = vertical transform index (taps ky), j = horizontal (kx), c = input channel, k = output channel of the slice.
 * TBASE is the kernels' compile-time constant (release/profile-mfg/origin.json): 3025 in 2304-byte models, 6049 in
 * 4608-byte models, 18049 in 18432-byte models, 72193 in 73728-byte models. The two larger sizes get the segment only
 * while their F4Q2 layer is on. The FP16 U'/2 table (bits 1 and 4) holds half ((s * 6 + i) * 192 + (c * 6 + j) * 2) * 8
 * + k = FP16(U'/2) rounded to nearest even. Logged: verdicts and counts only; nothing of a weight, coefficient or table
 * is logged or kept.
 */
#define F4Q_SLICE 2304u       /* float4 per 16->16 slice: 6 rows x 16 input channels x 6 columns x 4 float4 */
#define F4Q_TBASE_2304 3025u  /* float4 index of the segment in a 2304-byte model: (11520 + 16400 + 12288 + 8192) / 16 */
#define F4Q_TBASE_4608 6049u  /* 4608-byte model: (23040 + 32784 + 24576 + 16384) / 16 */
enum { F4Q_OFF = 0, F4Q_ON = 1, F4Q_SHADOW = 2 };
static UINT f4q_mode;         /* this context's mode, set by f4q_configure (fast_prepare) before any model or pipeline */
static LONG f4q_models[2];
static UINT model_f4q_size(UINT bytes);
#define F4Q2_TBASE_18432 18049u  /* float4 index of the segment in an 18432-byte model: (92160 + 131088 + 65536) / 16 */
#define F4Q2_TBASE_73728 72193u  /* 73728-byte model: (368640 + 524304 + 262144) / 16 */
#define F4Q2_1A3B 0x1a3b0782583fef19ULL
#define F4Q2_E83E 0xe83e868f8d5d2c0fULL
#define F4Q2_9E00 0x9e0080eee00255f2ULL
static UINT f4q2_mask;        /* this context's F4Q2 layers: bit 1 = 1a3b0782, 2 = e83e868f, 4 = 9e0080ee (f4q_configure) */
static LONG f4q2_models[2];
static UINT f4q2_bit(uint64_t h){UINT b=h==F4Q2_1A3B?1u:h==F4Q2_E83E?2u:h==F4Q2_9E00?4u:0u;return f4q2_mask&b;}
#define F4Q3_60ED 0x60edebbbd2f9fb69ULL
#define F4Q3_B3DD 0xb3ddf030f661d487ULL
static UINT f4q3_mask;        /* this context's F4Q3 row layers: bit 1 = 60edebbb, 2 = b3ddf030 (f4q_configure) */
static UINT f4q3_bit(uint64_t h){UINT b=h==F4Q3_60ED?1u:h==F4Q3_B3DD?2u:0u;return f4q3_mask&b;}
#define FP16_F4Q2 1u          /* the FP16 forms' bits (above) */
#define FP16_XU1 2u
#define FP16_F4Q 4u
#define FP16_ROW 8u
#define FP16_DEFAULT (FP16_F4Q2|FP16_XU1)   /* the forms this build turns on (bits 4 and 8 have no files in its package) */
static UINT fp16_mask;        /* this context's FP16 forms (f4q_configure), before any model or pipeline */
static LONG fp16_models;
static uint16_t model_half_int(int v);   /* src/model_wino_enc16.h */
static int f4q_env_word(const char*name,int*value){
 char v[16]={0};DWORD n=GetEnvironmentVariableA(name,v,sizeof(v));if(!n||n>=sizeof(v))return 0;
 if(!strcmp(v,"0")||!lstrcmpiA(v,"off")||!lstrcmpiA(v,"false")||!lstrcmpiA(v,"no")){*value=0;return 1;}
 if(!strcmp(v,"1")||!lstrcmpiA(v,"on")||!lstrcmpiA(v,"true")||!lstrcmpiA(v,"yes")){*value=1;return 1;}
 return 0;
}
/* Offset in bytes of the F4Q segment in a model of this size (after every enc16-family segment), 0 without one. */
static UINT f4q_segment_offset(UINT bytes){
 UINT cs,chunks=model_enc16_layout(bytes,&cs);if(!chunks)return 0;
 return model_enc16_offset(bytes)+chunks*16384u+16u+model_row16_size(bytes)+model_ref64_size(bytes)+model_f16_size(bytes);
}
static void f4q2_configure(void);
static void fp16_configure(void);
static void f4q3_configure(void);
/* F4Q's mode: on, its diagnostic (shadow) or off */
static void f4q_configure_mode(void){
 f4q_mode=F4Q_OFF;InterlockedExchange(&f4q_models[0],0);InterlockedExchange(&f4q_models[1],0);
 int on=1,shadow=0;const char*source="default";
 if(f4q_env_word("BC250_XEFG_F4Q",&on))source="BC250_XEFG_F4Q";
 else{UINT saved=mfg_settings_read_uint(L"F4Q",1);on=saved!=0;if(!on)source="settings.ini";}
 if(on&&(f4q_segment_offset(2304)!=F4Q_TBASE_2304*16u||f4q_segment_offset(4608)!=F4Q_TBASE_4608*16u)){
  logline("F4Q_CONFIG mode=off source=layout (the model layout does not give the F4Q kernels' segment offsets; the F(2x2) kernels run)\n");
  return;
 }
 if(on&&f4q_env_word("BC250_XEFG_F4Q_SHADOW",&shadow)&&shadow){
  f4q_mode=F4Q_SHADOW;
  logline("F4Q_CONFIG mode=shadow source=BC250_XEFG_F4Q_SHADOW (diagnostic: the F(2x2) kernels keep the output; the F4Q kernels run beside them and are compared on the GPU)\n");
  return;
 }
 f4q_mode=on?F4Q_ON:F4Q_OFF;
 char line[240];
 snprintf(line,sizeof(line),on?"F4Q_CONFIG mode=on source=%s (F(4x4) kernels for b3941ac8 and f030948d; identical to F(2x2) in every test, not proven for every input; BC250_XEFG_F4Q=0 or settings.ini F4Q=0 turns them off)\n":
          "F4Q_CONFIG mode=off source=%s (the F(2x2) kernels run)\n",source);logline(line);
}
/* After install_model_owner (which reads the profile's enc16 marker), before the runtime creates a model or pipeline:
 * F4Q's mode, then F4Q2, the FP16 forms and F4Q3 (which yields the row layers to bit 8 of the FP16 forms). */
static void f4q_configure(void){f4q_configure_mode();f4q2_configure();fp16_configure();f4q3_configure();}
/* F4Q2, after F4Q's mode: its layers follow F4Q (on, shadow or off) unless its own switch turns them off. */
static void f4q2_configure(void){
 f4q2_mask=0;InterlockedExchange(&f4q2_models[0],0);InterlockedExchange(&f4q2_models[1],0);
 int on=1;const char*source="default";
 if(f4q_env_word("BC250_XEFG_F4Q2",&on))source="BC250_XEFG_F4Q2";
 else{UINT saved=mfg_settings_read_uint(L"F4Q2",1);on=saved!=0;if(!on)source="settings.ini";}
 UINT mask=(on&&f4q_mode!=F4Q_OFF)?7u:0u,dropped=0;
 if((mask&2)&&f4q_segment_offset(18432)!=F4Q2_TBASE_18432*16u){mask&=~2u;dropped|=2;}
 if((mask&4)&&f4q_segment_offset(73728)!=F4Q2_TBASE_73728*16u){mask&=~4u;dropped|=4;}
 f4q2_mask=mask;
 const char*f4q=f4q_mode==F4Q_ON?"on":f4q_mode==F4Q_SHADOW?"shadow":"off";
 char line[400];
 if(mask)snprintf(line,sizeof(line),"F4Q2_CONFIG mode=%s source=%s layers=%u f4q=%s dropped_by_layout=%u (F(4x4) kernels for "
                  "1a3b0782 (1), e83e868f (2) and 9e0080ee (4); identical to F(2x2) in every test, not proven for every input; "
                  "BC250_XEFG_F4Q2=0 or settings.ini F4Q2=0 turns them off)\n",f4q_mode==F4Q_SHADOW?"shadow":"on",source,mask,f4q,dropped);
 else snprintf(line,sizeof(line),"F4Q2_CONFIG mode=off source=%s layers=0 f4q=%s dropped_by_layout=%u (the F(2x2) kernels run for "
               "1a3b0782, e83e868f and 9e0080ee)\n",on?(f4q_mode==F4Q_OFF?"F4Q":"layout"):source,f4q,dropped);
 logline(line);
}
/* F4Q3, last: the row layers follow F4Q (on, shadow or off) unless the FP16 forms run them (bit 8). */
static void f4q3_configure(void){
 f4q3_mask=f4q_mode!=F4Q_OFF&&!(fp16_mask&FP16_ROW)?3u:0u;
 const char*f4q=f4q_mode==F4Q_ON?"on":f4q_mode==F4Q_SHADOW?"shadow":"off";
 char line[320];
 if(f4q3_mask)snprintf(line,sizeof(line),"F4Q3_CONFIG mode=%s layers=3 f4q=%s (F(4x4) kernels for the row layers 60edebbb (1) and "
                       "b3ddf030 (2); identical to their 1D kernel in every test, not proven for every input)\n",f4q_mode==F4Q_SHADOW?"shadow":"on",f4q);
 else snprintf(line,sizeof(line),"F4Q3_CONFIG mode=off layers=0 f4q=%s source=%s (60edebbb and b3ddf030 run %s)\n",f4q,
               f4q_mode==F4Q_OFF?"F4Q":"FP16",f4q_mode==F4Q_OFF?"their 1D kernel":"their FP16 form");
 logline(line);
}
/* ---- the FP16 forms' model side */
/* float4 index of the PK copy per model size: the WINO16_BASE / ROW16_BASE of the six packed-FP16 kernels */
static UINT fp16_pk_base(UINT bytes){
 return bytes==2304?5329u:bytes==4608?10657u:bytes==9216?9025u:bytes==18432?36481u:bytes==36864?86018u:bytes==73728?145921u:0u;
}
/* float4 index of the half copy (2304 / 4608 only): the TBASE of 1a3b0782's, b3941ac8's and f030948d's FP16 kernels */
static UINT fp16_half_base(UINT bytes){return bytes==2304?5713u:bytes==4608?11425u:0u;}
/* the F4Q segment's full size for a size that can carry one (2304, 4608: F4Q; 18432, 73728: F4Q2), else 0 */
static UINT fp16_f4q_room(UINT bytes){
 UINT cs,chunks=model_enc16_layout(bytes,&cs);
 return chunks&&(bytes==2304||bytes==4608||bytes==18432||bytes==73728)?chunks*F4Q_SLICE*16u:0;
}
/* bytes of the PK copy: the row16 segment for 2304 / 4608, the enc16 segment for the others (the FP16 marker bit 1024) */
static UINT fp16_pk_copy(UINT bytes){
 UINT cs,chunks=model_enc16_layout(bytes,&cs);if(!chunks||!fp16_pk_base(bytes))return 0;
 if(bytes==2304||bytes==4608)return model_row16_size(bytes)?chunks*6144u:0;
 return (model_wino_enc16&1024)?chunks*8192u:0;
}
static UINT fp16_halfc_size(UINT bytes){UINT cs,chunks=model_enc16_layout(bytes,&cs);return (bytes==2304||bytes==4608)&&chunks?chunks*F4Q_SLICE*8u:0;}
static UINT fp16_pk_wanted(UINT bytes){
 if(bytes==2304||bytes==4608)return fp16_mask&FP16_ROW;
 return bytes==9216||bytes==18432||bytes==36864||bytes==73728?fp16_mask&FP16_XU1:0u;
}
static UINT fp16_halfc_wanted(UINT bytes){
 if(bytes==2304)return ((fp16_mask&FP16_F4Q2)&&(f4q2_mask&1u))||(fp16_mask&FP16_F4Q);
 return bytes==4608?fp16_mask&FP16_F4Q:0u;
}
static UINT fp16_pk_offset(UINT bytes){return f4q_segment_offset(bytes)+fp16_f4q_room(bytes);}
static UINT fp16_half_offset(UINT bytes){return fp16_pk_offset(bytes)+fp16_pk_copy(bytes);}
/* bytes after the F4Q segment (src/model_wino_enc16.h model_enc16_size): the rest of the F4Q room, the PK room and the half
 * copy, when a copy is wanted; 0 otherwise */
static UINT model_fp16_size(UINT bytes){
 UINT pk=fp16_pk_wanted(bytes)?fp16_pk_copy(bytes):0u,h=fp16_halfc_wanted(bytes)?fp16_halfc_size(bytes):0u;
 if(!pk&&!h)return 0;
 return fp16_f4q_room(bytes)-model_f4q_size(bytes)+fp16_pk_copy(bytes)+h;
}
/* The FP16 forms, after F4Q2's layers: on while F4Q is on (not its diagnostic) unless the exact switch is set; a bit
 * whose segment indices the model layout does not give is dropped. */
static void fp16_configure(void){
 fp16_mask=0;InterlockedExchange(&fp16_models,0);
 int exact=0;const char*source="default";
 if(f4q_env_word("BC250_XEFG_EXACT",&exact))source="BC250_XEFG_EXACT";
 else{UINT saved=mfg_settings_read_uint(L"Exact",0);exact=saved!=0;if(exact)source="settings.ini";}
 UINT mask=exact||f4q_mode!=F4Q_ON?0u:FP16_DEFAULT,dropped=0;
 static const UINT sizes[6]={2304,4608,9216,18432,36864,73728};
 for(UINT pass=0;pass<2;pass++){   /* a drop can only shrink what is wanted: two passes settle it */
  fp16_mask=mask;
  for(UINT i=0;i<6;i++){
   UINT s=sizes[i];
   if(fp16_pk_wanted(s)&&(!fp16_pk_copy(s)||fp16_pk_offset(s)!=fp16_pk_base(s)*16u)){
    UINT bit=s==2304||s==4608?FP16_ROW:FP16_XU1;mask&=~bit;dropped|=bit;
   }
   if(fp16_halfc_wanted(s)&&(!fp16_halfc_size(s)||fp16_half_offset(s)!=fp16_half_base(s)*16u)){
    UINT bit=s==2304?(FP16_F4Q2|FP16_F4Q):FP16_F4Q;dropped|=mask&bit;mask&=~bit;
   }
  }
 }
 fp16_mask=mask;
 const char*f4q=f4q_mode==F4Q_ON?"on":f4q_mode==F4Q_SHADOW?"shadow":"off";
 char line[480];
 if(mask)snprintf(line,sizeof(line),"FP16_CONFIG mode=on source=%s forms=%u f4q=%s f4q2=%u dropped=%u (FP16 forms of the U-Net kernels: 1 = the "
                  "F4Q2 encoders 1a3b0782 e83e868f 9e0080ee, 2 = 1f27b449 f2e2e13f 5654aa38 4bb52a63; the output differs slightly from "
                  "Intel's; BC250_XEFG_EXACT=1 or settings.ini Exact=1 turns them off)\n",
                  source,mask,f4q,f4q2_mask,dropped);
 else snprintf(line,sizeof(line),"FP16_CONFIG mode=off source=%s forms=0 f4q=%s f4q2=%u dropped=%u (%s)\n",
               exact?source:f4q_mode!=F4Q_ON?"F4Q":"layout",f4q,f4q2_mask,dropped,
               exact?"exact: every kernel in its exact form":f4q_mode!=F4Q_ON?"they need F4Q on":"the model layout does not give their segments");
 logline(line);
}
/* FP16 bits of u / 2 (|u| <= 73728), rounded to nearest even; *exact = representable */
static uint16_t fp16_half_of_half(int u,int*exact){
 UINT sign=u<0?0x8000u:0u,m=u<0?(UINT)-u:(UINT)u;*exact=1;if(!m)return (uint16_t)sign;
 int e=31-__builtin_clz(m),ex=e-1;UINT q;   /* 2^e <= m < 2^(e+1); u / 2 = (q / 1024) * 2^(e-1), q in [1024, 2048) */
 if(e<=10)q=m<<(10-e);
 else{UINT sh=(UINT)(e-10),r=m&((1u<<sh)-1u),half=1u<<(sh-1);q=m>>sh;*exact=!r;if(r>half||(r==half&&(q&1u)))q++;if(q==2048u){q=1024u;ex++;}}
 return (uint16_t)(sign|((UINT)(ex+15)<<10)|(q-1024u));
}
/* The FP16 U'/2 table of one model: half index ((s*6+i)*192 + (c*6+j)*2)*8 + k, the rest of its room untouched (the
 * caller zeroes it); returns 1 when every U'/2 was representable. */
static int fp16_half_table(const int8_t*raw,UINT chunks,uint16_t*half){
 static const int GP[6][3]={{6,0,0},{-4,-4,-4},{-4,4,-4},{1,2,4},{1,-2,4},{0,0,24}};int all=1;
 for(UINT s=0;s<chunks;s++)for(UINT k=0;k<16;k++)for(UINT c=0;c<16;c++){
  int g[3][3];for(UINT ky=0;ky<3;ky++)for(UINT kx=0;kx<3;kx++)g[ky][kx]=raw[s*2304+(ky*3+kx)*256+(c>>2)*64+k*4+(c&3)];
  for(UINT i=0;i<6;i++)for(UINT j=0;j<6;j++){
   int u=0;for(UINT a=0;a<3;a++)for(UINT b=0;b<3;b++)u+=GP[i][a]*g[a][b]*GP[j][b];
   if(u>73728||u<-73728)model_fail("F4Q coefficient bound");
   int exact;half[((s*6+i)*192u+(c*6+j)*2u)*8u+k]=fp16_half_of_half(u,&exact);all&=exact;
  }
 }
 return all;
}
/* From model_enc16_pack after the F4Q segment, under the model lock: zeros over the FP16 forms' region, then the PK copy
 * x 2^-8 (exact: every U is an integer, |U| <= 1152) and the half copy where wanted. seg: the FP32 enc16 segment. */
static void model_fp16_pack(void*snapshot,UINT bytes,const int8_t*raw,const float*seg){
 UINT total=model_fp16_size(bytes);if(!total)return;
 UINT cs,chunks=model_enc16_layout(bytes,&cs),start=f4q_segment_offset(bytes)+model_f4q_size(bytes);
 memset((char*)snapshot+start,0,total);
 UINT halves=0;int half=-1;
 if(fp16_pk_wanted(bytes)){
  UINT at=fp16_pk_offset(bytes);if(at!=fp16_pk_base(bytes)*16u)model_fail("FP16 PK segment offset (the kernels' WINO16_BASE / ROW16_BASE)");
  const float*src=bytes==2304||bytes==4608?seg+chunks*4096u+4u:seg;UINT count=bytes==2304||bytes==4608?chunks*3072u:chunks*4096u;
  uint16_t*h=(uint16_t*)((char*)snapshot+at);
  for(UINT i=0;i<count;i++){int u=(int)src[i];uint16_t b=model_half_int(u);h[i]=u?(uint16_t)(b-(8u<<10)):b;}
  halves=count;
 }
 if(fp16_halfc_wanted(bytes)){
  UINT at=fp16_half_offset(bytes);if(at!=fp16_half_base(bytes)*16u)model_fail("FP16 half copy offset (the kernels' TBASE)");
  half=fp16_half_table(raw,chunks,(uint16_t*)((char*)snapshot+at));
 }
 LONG k=InterlockedIncrement(&fp16_models);
 char line[200];snprintf(line,sizeof(line),"FP16_SEGMENT bytes=%u pk_base=%u pk_halves=%u half_base=%u half=%s models=%ld\n",bytes,
                         halves?fp16_pk_offset(bytes)/16u:0u,halves,half>=0?fp16_half_offset(bytes)/16u:0u,
                         half<0?"none":half?"exact":"rounded",(long)k);logline(line);
}
static UINT model_f4q_size(UINT bytes){
 if(f4q_mode!=F4Q_OFF&&((bytes==18432&&(f4q2_mask&2))||(bytes==73728&&(f4q2_mask&4)))){
  UINT cs;UINT chunks=model_enc16_layout(bytes,&cs);return chunks?chunks*F4Q_SLICE*16u:0;
 }
 if(f4q_mode==F4Q_OFF||(bytes!=2304&&bytes!=4608))return 0;
 UINT cs;UINT chunks=model_enc16_layout(bytes,&cs);if(!chunks)return 0;
 return chunks*F4Q_SLICE*16u;
}
/* Under the model lock, from model_enc16_pack after its segments: seg points at the F4Q segment (float4 index base). The
 * offset was checked for both sizes before any model existed (f4q_configure); the coefficient bound holds for every
 * int8 weight. Either check failing here means the model owner's layout is not the one this file was written for, so it
 * fails closed like the owner's other layout checks. */
static void model_f4q_pack(const int8_t*raw,UINT bytes,float*seg,UINT base_float4){
 UINT cs;UINT chunks=model_enc16_layout(bytes,&cs);if(!chunks||!model_f4q_size(bytes))return;
 UINT want=bytes==2304?F4Q_TBASE_2304:bytes==4608?F4Q_TBASE_4608:bytes==18432?F4Q2_TBASE_18432:F4Q2_TBASE_73728;
 if(base_float4!=want)model_fail("F4Q segment offset (the kernels' TBASE)");
 static const int GP[6][3]={{6,0,0},{-4,-4,-4},{-4,4,-4},{1,2,4},{1,-2,4},{0,0,24}};
 /* FP16 forms bit 1: the F4Q2 tables of 18432- / 73728-byte models (read only by e83e868f / 9e0080ee) as FP16 U'/2 pairs in
  * place, the rest of the segment zeroed */
 int half=(fp16_mask&FP16_F4Q2)&&(bytes==18432||bytes==73728),half_exact=1;
 if(half){memset(seg,0,chunks*F4Q_SLICE*16u);half_exact=fp16_half_table(raw,chunks,(uint16_t*)seg);}
 else
 for(UINT s=0;s<chunks;s++)for(UINT k=0;k<16;k++)for(UINT c=0;c<16;c++){
  int g[3][3];for(UINT ky=0;ky<3;ky++)for(UINT kx=0;kx<3;kx++)g[ky][kx]=raw[s*2304+(ky*3+kx)*256+(c>>2)*64+k*4+(c&3)];
  for(UINT i=0;i<6;i++)for(UINT j=0;j<6;j++){
   int u=0;for(UINT a=0;a<3;a++)for(UINT b=0;b<3;b++)u+=GP[i][a]*g[a][b]*GP[j][b];
   if(u>73728||u<-73728)model_fail("F4Q coefficient bound");
   seg[((s*6+i)*384u+(c*6+j)*4u+(k>>2))*4u+(k&3)]=(float)u;
  }
 }
 LONG n=bytes==2304?InterlockedIncrement(&f4q_models[0]):bytes==4608?InterlockedIncrement(&f4q_models[1]):
        InterlockedIncrement(&f4q2_models[bytes==18432?0:1]);
 char line[160];
 if(half)snprintf(line,sizeof(line),"F4Q_SEGMENT bytes=%u tbase=%u models=%ld form=fp16 fp16_exact=%d\n",bytes,want,(long)n,half_exact);
 else snprintf(line,sizeof(line),"F4Q_SEGMENT bytes=%u tbase=%u models=%ld\n",bytes,want,(long)n);
 logline(line);
}
