// SPDX-License-Identifier: MIT
// Winograd F(4x4,3x3) graph, pass 1: input transform of int8 activations into the transform domain.
#include "conv_wino4_common.hlsli"
#if defined(WINO_INPUT_I16) && F4_PREP_TILES < 8
#error Packed input stores need adjacent tile pairs
#endif
#if defined(WINO_U24) && defined(WINO_INPUT_I16) && (!defined(MICRO) || defined(WINO_F2))
#error Packed biased inputs require the private F4 micro allocation contract
#endif
#if F4_PREP_TILES >= 8
#define PREP_CHANNELS (64/F4_PREP_TILES)
// Adjacent tiles improve the domain-major buffer stores.
// Each invocation owns its horizontal scratch; no cross-thread exchange.
groupshared int16_t horizontal[WINO_DOMAIN*WINO_DOMAIN*64];
F4_ROOT
[numthreads(F4_PREP_TILES,PREP_CHANNELS,1)]
void main(uint3 group:SV_GroupID,uint3 tid:SV_GroupThreadID){
 uint tile=group.x*F4_PREP_TILES+tid.x,nx=(c1.x+WINO_TILE-1)/WINO_TILE,tx=tile%nx,ty=tile/nx,channel=group.y*PREP_CHANNELS+tid.y;
 if(tile>=tileStride())return;
 [loop]for(uint row=0;row<WINO_DOMAIN;row++){
  int v[6]={0,0,0,0,0,0};
  [unroll]for(uint dx=0;dx<WINO_DOMAIN;dx++){
   int x=(int)(tx*WINO_TILE+dx)-1;uint y=ty*WINO_TILE+row;WINO_TEXEL word=0;
   if(x>=0&&x<(int)c0.z&&y>0&&y<=c0.w)word=activations.Load(int4(x,y,channel/WINO_PACK,0));
   v[dx]=byteLane(word[(channel/4)%(WINO_PACK/4)],channel%4);
  }
  [unroll]for(uint dx=0;dx<WINO_DOMAIN;dx++)horizontal[((dx*WINO_DOMAIN+row)*PREP_CHANNELS+tid.y)*F4_PREP_TILES+tid.x]=(int16_t)bt(dx,v[0],v[1],v[2],v[3],v[4],v[5]);
 }
 [loop]for(uint dx=0;dx<WINO_DOMAIN;dx++){
  int v[6]={0,0,0,0,0,0};[unroll]for(uint y=0;y<WINO_DOMAIN;y++)v[y]=(int)horizontal[((dx*WINO_DOMAIN+y)*PREP_CHANNELS+tid.y)*F4_PREP_TILES+tid.x];
  [unroll]for(uint dy=0;dy<WINO_DOMAIN;dy++){
   uint index=((dy*WINO_DOMAIN+dx)*WINO_CHANNELS+channel)*tileStride()+tile;
   int transformed=bt(dy,v[0],v[1],v[2],v[3],v[4],v[5]);
#ifdef WINO_INPUT_I16
   // Adjacent X quad lanes own adjacent tiles of the same channel. One lane
   // writes both halves; no two invocations update the same 32-bit word.
#ifdef WINO_U24
   // F4 transforms are bounded by +/-12800. The original +16384 bias
   // fits losslessly in uint16; the consumer keeps the same U24 correction.
   transformed+=16384;
#endif
   uint neighbour=asuint(QuadReadAcrossX(transformed));
   if((tid.x&1)==0)inputDomains.Store(index*2,(asuint(transformed)&65535)|(neighbour<<16));
#else
#ifdef WINO_U24
   inputDomains[index]=(uint)(transformed+16384);
#else
   inputDomains[index]=(float)transformed;
#endif
#endif
  }
 }
}
#else
groupshared int16_t horizontal[WINO_DOMAIN*WINO_DOMAIN*8];
F4_ROOT
[numthreads(8,8,1)]
void main(uint3 group:SV_GroupID,uint3 tid:SV_GroupThreadID){
 uint tile=group.x,nx=(c1.x+WINO_TILE-1)/WINO_TILE,tx=tile%nx,ty=tile/nx,channel=group.y*8+tid.x;
 if(tid.y<WINO_DOMAIN){
  int v[6]={0,0,0,0,0,0};
  [unroll]for(uint dx=0;dx<WINO_DOMAIN;dx++){
   int x=(int)(tx*WINO_TILE+dx)-1;uint y=ty*WINO_TILE+tid.y;WINO_TEXEL word=0;
   if(x>=0&&x<(int)c0.z&&y>0&&y<=c0.w)word=activations.Load(int4(x,y,channel/WINO_PACK,0));
   v[dx]=byteLane(word[(channel/4)%(WINO_PACK/4)],channel%4);
  }
  [unroll]for(uint dx=0;dx<WINO_DOMAIN;dx++)horizontal[(tid.y*WINO_DOMAIN+dx)*8+tid.x]=(int16_t)bt(dx,v[0],v[1],v[2],v[3],v[4],v[5]);
 }
 GroupMemoryBarrierWithGroupSync();
 if(tid.y<WINO_DOMAIN){
  [unroll]for(uint dx=0;dx<WINO_DOMAIN;dx++){
   int v[6]={0,0,0,0,0,0};[unroll]for(uint y=0;y<WINO_DOMAIN;y++)v[y]=(int)horizontal[(y*WINO_DOMAIN+dx)*8+tid.x];
#ifdef WINO_U24
   inputDomains[((tid.y*WINO_DOMAIN+dx)*WINO_CHANNELS+channel)*tileStride()+tile]=(uint)(bt(tid.y,v[0],v[1],v[2],v[3],v[4],v[5])+16384);
#else
   inputDomains[((tid.y*WINO_DOMAIN+dx)*WINO_CHANNELS+channel)*tileStride()+tile]=(float)bt(tid.y,v[0],v[1],v[2],v[3],v[4],v[5]);
#endif
  }
 }
}
#endif
