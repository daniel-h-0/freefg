// SPDX-License-Identifier: MIT
// Winograd F(4x4,3x3) graph, pass 2: transform-domain matrix products with int16 coefficients (exact integer arithmetic).
#ifdef COOP_VECTOR
#define WINO_INPUT_RAW 1
#endif
#if defined(WINO_INPUT_I16) && !defined(COOP_VECTOR)
#error Packed inputs require vector staging
#endif
#if defined(WINO_U24) && defined(WINO_INPUT_I16) && (!defined(MICRO) || defined(WINO_F2))
#error Packed biased inputs require the private F4 micro allocation contract
#endif
#if defined(WINO_U24) && (!defined(COOP_VECTOR) || !defined(WEIGHTS_I16))
#error Biased integer math requires vector I16 coefficient staging
#endif
#include "conv_wino4_common.hlsli"
#ifndef F4_M
#define F4_M 16
#endif
#ifndef F4_K_UNROLL
#define F4_K_UNROLL 16
#endif
#if defined(F4_TOTAL_CORRECTION) && (!defined(MICRO) || !defined(F4_DEFER_CORRECTION) || !defined(WINO_U24) || defined(WINO_F2))
#error Prepared total correction requires the paired private U24/F4 micro model
#endif
#if defined(F4_SEED_CORRECTION) && !defined(F4_TOTAL_CORRECTION)
#error Seeded correction requires the prepared total model tail
#endif
#ifdef F4_RELAXED
#define F4_PRECISE
#else
#define F4_PRECISE precise
#endif
#ifdef WEIGHTS_I16
#define WEIGHT_DATA (WINO_CHANNELS*2)
#define WEIGHT_STRIDE (WINO_CHANNELS/8)
#else
#define WEIGHT_DATA (WINO_CHANNELS*4)
#define WEIGHT_STRIDE (WINO_CHANNELS/4)
#endif
#ifdef WINO_U24
#define WEIGHT_HEADER (WINO_CHANNELS/4)
#elif defined(WINO_F2)
#define WEIGHT_HEADER 0
#else
#define WEIGHT_HEADER 2
#endif
#define WEIGHT_BLOCK (WEIGHT_DATA+WEIGHT_HEADER)
#ifdef WINO_U24
#define LDS_VALUE uint16_t
#define SUM_VALUE uint
#else
#define SUM_VALUE int
#ifdef WINO_HALF_LDS
#ifndef WINO_F2
#error Half storage is proven exact only for F2 input and coefficient bounds
#endif
#define LDS_VALUE float16_t
#else
#define LDS_VALUE float
#endif
#endif
#ifndef F4_LDS_PAD
#define F4_LDS_PAD 0
#endif
#if F4_LDS_PAD != 0 && F4_LDS_PAD != 1 && F4_LDS_PAD != 2 && F4_LDS_PAD != 4 && F4_LDS_PAD != 8
#error Unsupported matrix shared-memory padding
#endif
#if F4_LDS_PAD && (!defined(MICRO) || !defined(WINO_FAMILY64) || !defined(WINO_U24))
#error Shared-memory padding is a private U24 refinement experiment
#endif
#define WEIGHT_LDS_PITCH (F4_M+F4_LDS_PAD)
#define INPUT_LDS_PITCH (F4_N+F4_LDS_PAD)
#ifdef F4_PINGPONG
#define F4_SLOTS 2
#else
#define F4_SLOTS 1
#endif
groupshared LDS_VALUE weightTile[F4_SLOTS*16*WEIGHT_LDS_PITCH];
groupshared LDS_VALUE inputTile[F4_SLOTS*16*INPUT_LDS_PITCH];
#if defined(F4_PREFETCH) || defined(F4_PINGPONG)
#if !defined(MICRO) || !defined(WINO_U24) || !defined(COOP_VECTOR) || !defined(WEIGHTS_I16) || defined(WINO_INPUT_I16) || defined(WINO_F2) || F4_M != 32 || F4_N != 32 || F4_LDS_PAD != 0 || defined(F4_DEFER_CORRECTION) || defined(F4_SHARED_CORRECTION)
#error Buffering is a private U24/F4 M32/N32 experiment with the original correction
#endif
#if defined(F4_PREFETCH) && defined(F4_PINGPONG)
#error Select register prefetch or shared-memory ping-pong
#endif
#ifndef F4_PREFETCH_PARTS
#define F4_PREFETCH_PARTS 3
#endif
#if F4_PREFETCH_PARTS < 1 || F4_PREFETCH_PARTS > 3
#error Invalid prefetch resource selection
#endif
struct PendingTile { uint4 weight; uint4 input0; uint4 input1; };
PendingTile fetchTile(uint thread,uint3 group,uint ci,uint stride,uint parts){
 PendingTile value;value.weight=0;value.input0=0;value.input1=0;
 uint base=WINO_PREFIX+(group.z*(WINO_CHANNELS/16)+ci)*WEIGHT_BLOCK;
 uint k=thread/4,col=(thread%4)*8,output=group.y*32+col;
 if(parts&1)value.weight=weights[base+WEIGHT_HEADER+k*WEIGHT_STRIDE+output/8];
 k=thread/8;col=(thread%8)*4;
 if(parts&2){
 value.input0=inputDomains.Load4(4*((group.z*WINO_CHANNELS+ci*16+k)*stride+group.x*32+col));
 value.input1=inputDomains.Load4(4*((group.z*WINO_CHANNELS+ci*16+k+8)*stride+group.x*32+col));
 }
 return value;
}
void storeTile(uint thread,PendingTile value,uint slot){
 uint offset=slot*512,k=thread/4,col=(thread%4)*8;
 [unroll]for(uint j=0;j<8;j++)weightTile[offset+k*32+col+j]=(uint16_t)(value.weight[j/2]>>(16*(j%2)));
 k=thread/8;col=(thread%8)*4;
 [unroll]for(uint j=0;j<4;j++){
  inputTile[offset+k*32+col+j]=(uint16_t)value.input0[j];
  inputTile[offset+(k+8)*32+col+j]=(uint16_t)value.input1[j];
 }
}
#endif
#ifdef F4_SHARED_CORRECTION
#if !defined(WINO_U24) || defined(F4_DEFER_CORRECTION)
#error Shared correction requires the original per-block U24 model
#endif
 groupshared uint sharedInputCorrection[F4_N];
#endif
F4_ROOT
[numthreads(8,8,1)]
void main(uint3 group:SV_GroupID,uint3 tid:SV_GroupThreadID){
#ifdef F4_SWAP_MATRIX_XY
#if !defined(MICRO) || !defined(WINO_FAMILY64) || defined(WINO_F2)
#error Matrix order experiment is limited to the private F4 refinement microbenchmark
#endif
 group=group.yxz;
#endif

 uint thread=tid.y*8+tid.x,domain=group.z,n=tileStride();SUM_VALUE total[F4_M/8][F4_N/8];
#ifdef F4_SEED_CORRECTION
 uint seedBase=WINO_PREFIX+36*(WINO_CHANNELS/16)*WEIGHT_BLOCK+domain*(WINO_CHANNELS/4);
 [unroll]for(uint m=0;m<F4_M/8;m++){
  uint output=group.y*F4_M+tid.y+m*8,correction=weights[seedBase+output/4][output%4];
  [unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]=0u-correction;
 }
#else
 [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]=0;
#endif
#ifdef F4_DEFER_CORRECTION
#ifndef WINO_U24
#error Deferred correction requires the exact biased U24 formulation
#endif
 uint inputSum[F4_N/8];
 [unroll]for(uint col=0;col<F4_N/8;col++)inputSum[col]=0;
#ifndef F4_TOTAL_CORRECTION
 uint coefficientSum[F4_M/8];
 [unroll]for(uint m=0;m<F4_M/8;m++)coefficientSum[m]=0;
#endif
#endif
#ifdef F4_PREFETCH
 PendingTile pending=fetchTile(thread,group,0,n,F4_PREFETCH_PARTS);
#endif
#ifdef F4_PINGPONG
 storeTile(thread,fetchTile(thread,group,0,n,3),0);
 GroupMemoryBarrierWithGroupSync();
#endif
 [loop]for(uint ci=0;ci<WINO_CHANNELS/16;ci++){
  uint sharedOffset=0;
#ifdef F4_PINGPONG
  sharedOffset=(ci&1)*512;
#else
  GroupMemoryBarrierWithGroupSync();
#endif
  uint base=WINO_PREFIX+(domain*(WINO_CHANNELS/16)+ci)*WEIGHT_BLOCK;
#ifdef F4_PINGPONG
  [branch]if(ci+1<WINO_CHANNELS/16)storeTile(thread,fetchTile(thread,group,ci+1,n,3),(ci+1)&1);
#else
#ifdef F4_PREFETCH
  PendingTile current=pending;
#if F4_PREFETCH_PARTS != 3
  PendingTile immediate=fetchTile(thread,group,ci,n,3^F4_PREFETCH_PARTS);
#if !(F4_PREFETCH_PARTS & 1)
  current.weight=immediate.weight;
#endif
#if !(F4_PREFETCH_PARTS & 2)
  current.input0=immediate.input0;current.input1=immediate.input1;
#endif
#endif
  storeTile(thread,current,0);
#else
#ifdef COOP_VECTOR
#ifdef WEIGHTS_I16
  for(uint index=thread;index<16*F4_M/8;index+=64){
   uint k=index/(F4_M/8),col=(index%(F4_M/8))*8,output=group.y*F4_M+col;
   uint4 value=weights[base+WEIGHT_HEADER+k*WEIGHT_STRIDE+output/8];
#ifdef WINO_U24
   [unroll]for(uint j=0;j<8;j++)weightTile[k*WEIGHT_LDS_PITCH+col+j]=(uint16_t)(value[j/2]>>(16*(j%2)));
#else
   [unroll]for(uint j=0;j<8;j++)weightTile[k*WEIGHT_LDS_PITCH+col+j]=(float)((int)(value[j/2]<<(16-16*(j%2)))>>16);
#endif
  }
#else
  for(uint index=thread;index<16*F4_M/4;index+=64){
   uint k=index/(F4_M/4),col=(index%(F4_M/4))*4,output=group.y*F4_M+col;
   float4 value=asfloat(weights[base+WEIGHT_HEADER+k*WEIGHT_STRIDE+output/4]);
   [unroll]for(uint j=0;j<4;j++)weightTile[k*WEIGHT_LDS_PITCH+col+j]=value[j];
  }
#endif
#ifdef WINO_INPUT_I16
  for(uint index=thread;index<16*F4_N/8;index+=64){
   uint k=index/(F4_N/8),col=(index%(F4_N/8))*8;
   uint4 value=inputDomains.Load4(2*((domain*WINO_CHANNELS+ci*16+k)*n+group.x*F4_N+col));
#ifdef WINO_U24
   [unroll]for(uint j=0;j<8;j++)inputTile[k*INPUT_LDS_PITCH+col+j]=(LDS_VALUE)((value[j/2]>>(16*(j%2)))&65535);
#else
   [unroll]for(uint j=0;j<8;j++)inputTile[k*INPUT_LDS_PITCH+col+j]=(LDS_VALUE)((int)(value[j/2]<<(16-16*(j%2)))>>16);
#endif
  }
#else
  for(uint index=thread;index<16*F4_N/4;index+=64){
   uint k=index/(F4_N/4),col=(index%(F4_N/4))*4;
#ifdef WINO_U24
   uint4 value=inputDomains.Load4(4*((domain*WINO_CHANNELS+ci*16+k)*n+group.x*F4_N+col));
#else
   float4 value=asfloat(inputDomains.Load4(4*((domain*WINO_CHANNELS+ci*16+k)*n+group.x*F4_N+col)));
#endif
   [unroll]for(uint j=0;j<4;j++)inputTile[k*INPUT_LDS_PITCH+col+j]=(LDS_VALUE)value[j];
  }
#endif
#else
  for(uint index=thread;index<16*F4_M;index+=64){
   uint k=index/F4_M,col=index%F4_M,output=group.y*F4_M+col;
#ifdef WEIGHTS_I16
   uint word=weights[base+WEIGHT_HEADER+k*WEIGHT_STRIDE+output/8][(output/2)%4];
   weightTile[(index/F4_M)*WEIGHT_LDS_PITCH+index%F4_M]=(float)((int)(word<<(16-16*(output%2)))>>16);
#else
   weightTile[(index/F4_M)*WEIGHT_LDS_PITCH+index%F4_M]=asfloat(weights[base+WEIGHT_HEADER+k*WEIGHT_STRIDE+output/4][output%4]);
#endif
  }
  for(uint index=thread;index<16*F4_N;index+=64){
   uint k=index/F4_N,col=index%F4_N;
   inputTile[(index/F4_N)*INPUT_LDS_PITCH+index%F4_N]=inputDomains[(domain*WINO_CHANNELS+ci*16+k)*n+group.x*F4_N+col];
  }
#endif
#endif // F4_PREFETCH
  GroupMemoryBarrierWithGroupSync();
#endif // F4_PINGPONG
#ifdef F4_PREFETCH
  // Current operands are now in LDS. Keep next operands in registers while
  // computing this tile; the final iteration performs no out-of-range fetch.
  [branch]if(ci+1<WINO_CHANNELS/16)pending=fetchTile(thread,group,ci+1,n,F4_PREFETCH_PARTS);
#endif
#ifdef F4_SHARED_CORRECTION
  if(thread<F4_N){
   uint sum=0;[unroll]for(uint k=0;k<16;k++)sum+=(uint)inputTile[sharedOffset+k*INPUT_LDS_PITCH+thread];
   sharedInputCorrection[thread]=sum<<13;
  }
  GroupMemoryBarrierWithGroupSync();
#endif
#ifdef WINO_U24
#if !defined(F4_DEFER_CORRECTION) && !defined(F4_SHARED_CORRECTION)
  uint inputSum[F4_N/8];[unroll]for(uint col=0;col<F4_N/8;col++)inputSum[col]=0;
#endif
  [loop]for(uint start=0;start<16;start+=F4_K_UNROLL)[unroll]for(uint offset=0;offset<F4_K_UNROLL;offset++){
   uint k=start+offset;
#ifndef F4_SHARED_CORRECTION
   [unroll]for(uint col=0;col<F4_N/8;col++)inputSum[col]+=(uint)inputTile[sharedOffset+k*INPUT_LDS_PITCH+tid.x+col*8];
#endif
   [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]=mad((uint)weightTile[sharedOffset+k*WEIGHT_LDS_PITCH+tid.y+m*8],(uint)inputTile[sharedOffset+k*INPUT_LDS_PITCH+tid.x+col*8],total[m][col]);
  }
#ifndef F4_TOTAL_CORRECTION
  [unroll]for(uint m=0;m<F4_M/8;m++){
   uint output=group.y*F4_M+tid.y+m*8,correction=weights[base+output/4][output%4];
#ifdef F4_SHARED_CORRECTION
   [unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]-=sharedInputCorrection[tid.x+col*8]+correction;
#elif defined(F4_DEFER_CORRECTION)
   coefficientSum[m]+=correction;
#else
   [unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]-=(inputSum[col]<<13)+correction;
#endif
  }
#endif
#else
  bool fast=true;
#ifndef WINO_F2
  [unroll]for(uint m=0;m<F4_M/8;m++){uint output=group.y*F4_M+tid.y+m*8;uint flags=weights[base+output/128][(output/32)%4];fast=fast&&((flags&(1u<<(output%32)))!=0);}
#endif
  [branch]if(fast){
   F4_PRECISE float partial[F4_M/8][F4_N/8];[unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)partial[m][col]=0;
   [loop]for(uint start=0;start<16;start+=F4_K_UNROLL)[unroll]for(uint offset=0;offset<F4_K_UNROLL;offset++){
    uint k=start+offset;
    [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)partial[m][col]=mad((float)weightTile[sharedOffset+k*WEIGHT_LDS_PITCH+tid.y+m*8],(float)inputTile[sharedOffset+k*INPUT_LDS_PITCH+tid.x+col*8],partial[m][col]);
   }
   [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]+=(int)partial[m][col];
  }else{
   int partial[F4_M/8][F4_N/8];[unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)partial[m][col]=0;
   [loop]for(uint start=0;start<16;start+=F4_K_UNROLL)[unroll]for(uint offset=0;offset<F4_K_UNROLL;offset++){
    uint k=start+offset;
    [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)partial[m][col]+=(int)weightTile[sharedOffset+k*WEIGHT_LDS_PITCH+tid.y+m*8]*(int)inputTile[sharedOffset+k*INPUT_LDS_PITCH+tid.x+col*8];
   }
   [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]+=partial[m][col];
  }
#endif
#ifdef F4_PINGPONG
  // All reads of this slot and writes of the next slot finish before reuse.
  GroupMemoryBarrierWithGroupSync();
#endif
 }
#ifdef F4_DEFER_CORRECTION
 // Addition/subtraction and the fixed shift distribute modulo 2^32.
#ifdef F4_SEED_CORRECTION
 [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]-=inputSum[col]<<13;
#elif defined(F4_TOTAL_CORRECTION)
 uint correctionBase=WINO_PREFIX+36*(WINO_CHANNELS/16)*WEIGHT_BLOCK+domain*(WINO_CHANNELS/4);
 [unroll]for(uint m=0;m<F4_M/8;m++){
  uint output=group.y*F4_M+tid.y+m*8,correction=weights[correctionBase+output/4][output%4];
  [unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]-=(inputSum[col]<<13)+correction;
 }
#else
 [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++)total[m][col]-=(inputSum[col]<<13)+coefficientSum[m];
#endif
#endif
 [unroll]for(uint m=0;m<F4_M/8;m++)[unroll]for(uint col=0;col<F4_N/8;col++){
  uint output=group.y*F4_M+tid.y+m*8,tile=group.x*F4_N+tid.x+col*8;
  outputDomains[(domain*n+tile)*WINO_CHANNELS+output]=total[m][col];
 }
}
