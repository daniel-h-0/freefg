// SPDX-License-Identifier: MIT
// Optional generated-frame enlargement; the original bilinear shader is retained.
#ifndef BC250_UP_FILTER
#error Select an enlargement filter
#endif
Texture2D<float4> lowFrame:register(t0);
RWTexture2D<float4> generated:register(u0);
SamplerState linearClamp:register(s0);

#if BC250_UP_FILTER == 4
#define A_GPU 1
#define A_HLSL 1
#define FSR_EASU_F 1
#include "../vendor/fsr1/ffx_a.h"
cbuffer EasuConstants:register(b0){uint4 c0,c1,c2,c3;}
AF4 FsrEasuRF(AF2 p){return lowFrame.GatherRed(linearClamp,p);}
AF4 FsrEasuGF(AF2 p){return lowFrame.GatherGreen(linearClamp,p);}
AF4 FsrEasuBF(AF2 p){return lowFrame.GatherBlue(linearClamp,p);}
#include "../vendor/fsr1/ffx_fsr1.h"
#else
float cubic(float x) {
 x=abs(x);
 return x<1 ? ((1.5*x-2.5)*x)*x+1 : x<2 ? ((-0.5*x+2.5)*x-4)*x+2 : 0;
}
float sinc(float x) {
 x=abs(x);if(x<0.00001)return 1;
 float p=3.14159265358979323846*x;return sin(p)/p;
}
float kernel(float x) {
#if BC250_UP_FILTER == 2
 return cubic(x);
#elif BC250_UP_FILTER == 3
 return abs(x)<2 ? sinc(x)*sinc(x*0.5) : 0;
#else
#error Unsupported enlargement filter
#endif
}
float4 reconstruct(float2 pos,int2 size) {
 int2 origin=int2(floor(pos));float2 fraction=pos-float2(origin);
 float4 wx,wy;
 [unroll]for(int i=0;i<4;i++){wx[i]=kernel(float(i-1)-fraction.x);wy[i]=kernel(float(i-1)-fraction.y);}
 wx/=dot(wx,float4(1,1,1,1));wy/=dot(wy,float4(1,1,1,1));
 float4 result=0;
 [unroll]for(int y=0;y<4;y++) {
  float4 row=0;
  [unroll]for(int x=0;x<4;x++)row+=lowFrame.Load(int3(clamp(origin+int2(x-1,y-1),int2(0,0),size-1),0))*wx[x];
  result+=row*wy[y];
 }
 return result;
}
#endif

#if BC250_UP_FILTER == 4
#define BC250_EASU_ROOT "RootConstants(num32BitConstants=16,b0),"
#else
#define BC250_EASU_ROOT ""
#endif
[RootSignature("DescriptorTable(SRV(t0)),DescriptorTable(UAV(u0))," BC250_EASU_ROOT "StaticSampler(s0,filter=FILTER_MIN_MAG_MIP_LINEAR,addressU=TEXTURE_ADDRESS_CLAMP,addressV=TEXTURE_ADDRESS_CLAMP,addressW=TEXTURE_ADDRESS_CLAMP)")]
[numthreads(8,8,1)]
void main(uint3 p:SV_DispatchThreadID) {
 uint width,height,iw,ih;generated.GetDimensions(width,height);lowFrame.GetDimensions(iw,ih);
 if(p.x>=width||p.y>=height)return;
 float2 uv=(float2(p.xy)+0.5)/float2(width,height);
#if BC250_UP_FILTER == 4
 AF3 rgb;FsrEasuF(rgb,p.xy,c0,c1,c2,c3);
 // EASU reconstructs RGB. Retain interpolated alpha instead of forcing opacity.
 generated[p.xy]=float4(rgb,lowFrame.SampleLevel(linearClamp,uv,0).a);
#else
 generated[p.xy]=float4(reconstruct(uv*float2(iw,ih)-0.5,int2(iw,ih)).rgb,lowFrame.SampleLevel(linearClamp,uv,0).a);
#endif
}
