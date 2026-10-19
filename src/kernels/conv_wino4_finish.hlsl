// SPDX-License-Identifier: MIT
// Winograd F(4x4,3x3) graph, pass 3: inverse transform, bias, clamp, dual-slope requantization and pack.
#include "conv_wino4_common.hlsli"
groupshared INVERSE_VALUE horizontal[24*WINO_FINISH_CHANNELS];
groupshared uint resultBytes[16*WINO_FINISH_CHANNELS];
F4_ROOT
[numthreads(WINO_FINISH_CHANNELS,8,1)]
void main(uint3 group:SV_GroupID,uint3 tid:SV_GroupThreadID){
 uint channel=group.y*WINO_FINISH_CHANNELS+tid.x,n=tileStride();
 if(tid.y<6){
  INVERSE_VALUE v[6];[unroll]for(uint dx=0;dx<6;dx++)v[dx]=(INVERSE_VALUE)outputDomains[((tid.y*6+dx)*n+group.x)*WINO_CHANNELS+channel];
  [unroll]for(uint x=0;x<4;x++)horizontal[(tid.y*4+x)*WINO_FINISH_CHANNELS+tid.x]=inverse(x,v[0],v[1],v[2],v[3],v[4],v[5]);
 }
 GroupMemoryBarrierWithGroupSync();
 if(tid.y<4){
  int bias=biases[channel/4][channel%4],slope=slopes[channel/4][channel%4];
  [unroll]for(uint x=0;x<4;x++){
   INVERSE_VALUE v[6];[unroll]for(uint y=0;y<6;y++)v[y]=horizontal[(y*4+x)*WINO_FINISH_CHANNELS+tid.x];
   INVERSE_VALUE sum=inverse(tid.y,v[0],v[1],v[2],v[3],v[4],v[5]);
   int value=inverse_result(sum);value=asint(asuint(value)+asuint(bias));
   resultBytes[(tid.y*4+x)*WINO_FINISH_CHANNELS+tid.x]=asuint(quantize(value,slope))&255;
  }
 }
 GroupMemoryBarrierWithGroupSync();
 if(tid.x%WINO_PACK==0&&tid.y<4){
  uint nx=(c1.x+3)/4;
  [unroll]for(uint x=0;x<4;x++){
   uint2 p=uint2((group.x%nx)*4+x,(group.x/nx)*4+tid.y);WINO_TEXEL v=0;
   [unroll]for(uint word=0;word<WINO_PACK/4;word++)[unroll]for(uint c=0;c<4;c++)v[word]|=resultBytes[(tid.y*4+x)*WINO_FINISH_CHANNELS+tid.x+c+word*4]<<(8*c);
   if(all(p<c1.xy))outputImage[uint3(p.x,p.y+1,channel/WINO_PACK)]=v;
  }
 }
}
