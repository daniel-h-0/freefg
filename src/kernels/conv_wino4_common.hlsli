// SPDX-License-Identifier: MIT
// Shared ABI for the owned-data three-pass Winograd experiment.
#if !defined(MICRO) && !defined(WINO_GRAPH)
#error Select the owned-data or private graph ABI
#endif
#ifdef WINO_FAMILY16
#define WINO_CHANNELS 16
#define WINO_PACK 16
#define WINO_TEXEL uint4
#elif defined(WINO_FAMILY64)
#define WINO_CHANNELS 64
#define WINO_PACK 16
#define WINO_TEXEL uint4
#else
#define WINO_CHANNELS 224
#define WINO_PACK 8
#define WINO_TEXEL uint2
#endif
#ifndef WINO_PREFIX
#define WINO_PREFIX (WINO_CHANNELS*WINO_CHANNELS*9/16)
#endif
#ifndef WINO_FINISH_CHANNELS
#define WINO_FINISH_CHANNELS WINO_PACK
#endif
#if WINO_FINISH_CHANNELS < WINO_PACK || WINO_FINISH_CHANNELS % WINO_PACK != 0
#error Finish groups must contain complete output texels
#endif
#ifdef MICRO_FLOAT_ACTIVATIONS
#if !defined(MICRO) || !defined(WINO_FAMILY16)
#error Expanded activation input is a private C16 microbenchmark
#endif
Texture2DArray<float4> activations:register(t0);
#else
Texture2DArray<WINO_TEXEL> activations:register(t0);
#endif
StructuredBuffer<uint4> weights:register(t1);
StructuredBuffer<int4> biases:register(t2);
StructuredBuffer<int4> slopes:register(t3);
RWTexture2DArray<WINO_TEXEL> outputImage:register(u0);
#if defined(WINO_INPUT_RAW) || defined(WINO_INPUT_I16)
RWByteAddressBuffer inputDomains:register(u1);
#else
#ifdef WINO_U24
RWStructuredBuffer<uint> inputDomains:register(u1);
#else
RWStructuredBuffer<float> inputDomains:register(u1);
#endif
#endif
RWStructuredBuffer<int> outputDomains:register(u2);
cbuffer Parameters:register(b0){uint4 c0;uint4 c1;uint4 c2;}
#ifdef WINO_GRAPH
#define F4_ROOT [RootSignature("DescriptorTable(SRV(t0),UAV(u0)), DescriptorTable(SRV(t1),SRV(t2),SRV(t3)), RootConstants(num32BitConstants=12,b0), UAV(u1), UAV(u2)")]
#else
#define F4_ROOT [RootSignature("DescriptorTable(SRV(t0)), SRV(t1), SRV(t2), SRV(t3), DescriptorTable(UAV(u0)), RootConstants(num32BitConstants=12,b0), UAV(u1), UAV(u2)")]
#endif
#ifdef WINO_F2
#define WINO_DOMAIN 4
#define WINO_TILE 2
#else
#define WINO_DOMAIN 6
#define WINO_TILE 4
#endif
#ifndef F4_N
#define F4_N 16
#endif
#ifndef WINO_PITCH_PAD
#define WINO_PITCH_PAD 0
#endif
#if WINO_PITCH_PAD != 0 && WINO_PITCH_PAD != 8 && WINO_PITCH_PAD != 16
#error Unsupported row padding
#endif
#if WINO_PITCH_PAD >= F4_N
#error Padding must be smaller than the matrix column tile
#endif
#if WINO_PITCH_PAD && (!defined(WINO_FAMILY64) || defined(WINO_F2))
#error Padded pitch is limited to the private F4 refinement family
#endif
uint tileCount(){return ((c1.x+WINO_TILE-1)/WINO_TILE)*((c1.y+WINO_TILE-1)/WINO_TILE);}
uint tileStride(){return ((tileCount()+F4_N-1)/F4_N)*F4_N+WINO_PITCH_PAD;}
int byteLane(uint word,uint lane){return (int)(word<<(24-8*lane))>>24;}
int bt(uint domain,int a,int b,int c,int d,int e,int f){
#ifdef WINO_F2
 switch(domain){case 0:return a-c;case 1:return b+c;case 2:return c-b;default:return b-d;}
#else
 switch(domain){case 0:return 4*a-5*c+e;case 1:return -4*b-4*c+d+e;case 2:return 4*b-4*c-d+e;case 3:return -2*b-c+2*d+e;case 4:return 2*b-c-2*d+e;default:return 4*b-5*d+f;}
#endif
}
#ifdef F4_MODULAR_INVERSE
#if WINO_CHANNELS > 224
#error The signed 26-bit recovery requires a checked convolution output bound
#endif
#define INVERSE_VALUE uint
#else
#define INVERSE_VALUE int64_t
#endif
INVERSE_VALUE inverse(uint component,INVERSE_VALUE a,INVERSE_VALUE b,INVERSE_VALUE c,INVERSE_VALUE d,INVERSE_VALUE e,INVERSE_VALUE f){
 a*=6;b*=4;c*=4;f*=24;
 INVERSE_VALUE signedC=(component&1)?-c:c,signedE=(component&1)?-e:e;
 return b+signedC+((d+signedE)<<component)+(component==0?a:0)+(component==3?f:0);
}
int inverse_result(INVERSE_VALUE sum){
#ifdef F4_MODULAR_INVERSE
 // sum == 576*convolution (mod 2^32). Divide its six zero bits, then
 // invert 9 modulo 2^26. |convolution| <= 224*9*128^2 < 2^25, so
 // signed 26-bit recovery is unique. Add the original bias afterwards.
 uint recovered=(sum>>6)*14913081u;
 return (int)(recovered<<6)>>6;
#else
 return (int)(sum>>6)/9;
#endif
}
#ifndef CLAMP_BITS
#define CLAMP_BITS 16
#endif
int quantize(int v,int slope){
 v=clamp(v,-(1<<CLAMP_BITS),(1<<CLAMP_BITS)-1);uint ps=c2.z&31,ns=(c2.z>>8)&31;
 int p=asint(asuint(max(v,0))*c2.y+(1u<<((ps+31)&31)));
 int n=asint(asuint(min(v,0))*asuint(slope)+(1u<<((ns+31)&31)));
 return clamp((p>>ps)+(n>>ns),-128,127);
}
