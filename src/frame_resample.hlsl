// SPDX-License-Identifier: MIT
// FreeFG colour resampling. No transfer-function conversion or range clamp:
// the SRV decodes its declared format and the destination stores float colour.
Texture2D<float4> source:register(t0);
RWTexture2D<float4> destination:register(u0);
SamplerState linearClamp:register(s0);
[RootSignature("DescriptorTable(SRV(t0)),DescriptorTable(UAV(u0)),StaticSampler(s0,filter=FILTER_MIN_MAG_MIP_LINEAR,addressU=TEXTURE_ADDRESS_CLAMP,addressV=TEXTURE_ADDRESS_CLAMP,addressW=TEXTURE_ADDRESS_CLAMP)")]
[numthreads(8,8,1)]
void main(uint3 p:SV_DispatchThreadID) {
 uint w,h,sw,sh;destination.GetDimensions(w,h);source.GetDimensions(sw,sh);
 if(p.x>=w||p.y>=h)return;
#if FREEFG_AREA
 float2 lo=float2(p.xy)*float2(sw,sh)/float2(w,h);
 float2 hi=float2(p.xy+1)*float2(sw,sh)/float2(w,h);
 float4 sum=0;float weight=0;
 for(int y=int(floor(lo.y));y<int(ceil(hi.y));y++)
  for(int x=int(floor(lo.x));x<int(ceil(hi.x));x++) {
   float2 overlap=max(0,min(hi,float2(x+1,y+1))-max(lo,float2(x,y)));
   float a=overlap.x*overlap.y;
   sum+=source.Load(int3(clamp(int2(x,y),int2(0,0),int2(sw,sh)-1),0))*a;weight+=a;
  }
 destination[p.xy]=sum/weight;
#else
 destination[p.xy]=source.SampleLevel(linearClamp,(float2(p.xy)+0.5)/float2(w,h),0);
#endif
}
