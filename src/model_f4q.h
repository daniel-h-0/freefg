/* SPDX-License-Identifier: MIT
 * F4Q (XEFG_F4Q, the multi-frame proxy since FreeFG 1.1): the model side of this project's FP32 Winograd F(4x4,3x3)
 * kernels for the U-Net decoder b3941ac8 (both sizes, 2304-byte models) and the encoder f030948d (4608-byte models),
 * src/kernels/f4q_dec16.hlsl and f4q_enc16.hlsl, which replace this project's F(2x2) kernels of those two pipelines
 * (src/game/f4q.h chooses the pipelines and their dispatch geometry). Their outputs matched the F(2x2) kernels' in every
 * test (20 SDK test rows; in-game comparisons on native 2x and OptiScaler 3x), but F(4x4) arithmetic rounds and no proof
 * covers every input: identical in every test, not proven for every input.
 *
 * Switch (read when a context is accelerated, f4q_configure):
 *   BC250_XEFG_F4Q=0 (also off, false, no)   F4Q off: the F(2x2) kernels run, as in 1.0.x
 *   BC250_XEFG_F4Q=1 (also on, true, yes)    F4Q on, whatever settings.ini says
 *   otherwise                                BC250-XeFG/settings.ini [BC250] F4Q=0 turns it off; on by default
 *   BC250_XEFG_F4Q_SHADOW=1                  diagnostic, only while F4Q is on: the F(2x2) kernels keep the output and the
 *                                            F4Q kernels run beside them; this project's own GPU passes count equal and
 *                                            differing outputs (src/game/f4q.h; nothing of the content is read)
 * F4Q also stays off when the model layout does not give the segment offsets the kernels were compiled for (below).
 *
 * The segment, appended after the enc16 family's segments of 2304- and 4608-byte models (src/model_wino_enc16.h), one
 * 16->16 slice per 2304-byte chunk s (raw layout tap * 256 + (cin / 4) * 64 + cout * 4 + cin % 4, as model_enc16_pack
 * reads it), U' = G' g G'^T with G' = 24 G, in FP32 (|U'| <= 128 * 24 * 24 = 73728 for every int8 g: exact):
 *   float4 index TBASE + (s * 6 + i) * 384 + (c * 6 + j) * 4 + q  = U'[i][j][c][4q .. 4q+3]
 * i = vertical transform index (taps ky), j = horizontal (kx), c = input channel, k = output channel of the slice.
 * TBASE is the kernels' compile-time constant (release/profile-mfg/origin.json): 3025 in 2304-byte models, 6049 in
 * 4608-byte models. Logged: verdicts and counts only; nothing of a weight, coefficient or table is logged or kept.
 */
#define F4Q_SLICE 2304u       /* float4 per 16->16 slice: 6 rows x 16 input channels x 6 columns x 4 float4 */
#define F4Q_TBASE_2304 3025u  /* float4 index of the segment in a 2304-byte model: (11520 + 16400 + 12288 + 8192) / 16 */
#define F4Q_TBASE_4608 6049u  /* 4608-byte model: (23040 + 32784 + 24576 + 16384) / 16 */
enum { F4Q_OFF = 0, F4Q_ON = 1, F4Q_SHADOW = 2 };
static UINT f4q_mode;         /* this context's mode, set by f4q_configure (fast_prepare) before any model or pipeline */
static LONG f4q_models[2];
static UINT model_f4q_size(UINT bytes);
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
/* After install_model_owner (which reads the profile's enc16 marker), before the runtime creates a model or pipeline. */
static void f4q_configure(void){
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
static UINT model_f4q_size(UINT bytes){
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
 UINT want=bytes==2304?F4Q_TBASE_2304:F4Q_TBASE_4608;
 if(base_float4!=want)model_fail("F4Q segment offset (the kernels' TBASE)");
 static const int GP[6][3]={{6,0,0},{-4,-4,-4},{-4,4,-4},{1,2,4},{1,-2,4},{0,0,24}};
 for(UINT s=0;s<chunks;s++)for(UINT k=0;k<16;k++)for(UINT c=0;c<16;c++){
  int g[3][3];for(UINT ky=0;ky<3;ky++)for(UINT kx=0;kx<3;kx++)g[ky][kx]=raw[s*2304+(ky*3+kx)*256+(c>>2)*64+k*4+(c&3)];
  for(UINT i=0;i<6;i++)for(UINT j=0;j<6;j++){
   int u=0;for(UINT a=0;a<3;a++)for(UINT b=0;b<3;b++)u+=GP[i][a]*g[a][b]*GP[j][b];
   if(u>73728||u<-73728)model_fail("F4Q coefficient bound");
   seg[((s*6+i)*384u+(c*6+j)*4u+(k>>2))*4u+(k&3)]=(float)u;
  }
 }
 UINT z=bytes==2304?0:1;LONG n=InterlockedIncrement(&f4q_models[z]);
 char line[120];snprintf(line,sizeof(line),"F4Q_SEGMENT bytes=%u tbase=%u models=%ld\n",bytes,want,(long)n);logline(line);
}
