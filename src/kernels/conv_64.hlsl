// SPDX-License-Identifier: MIT
// Runtime 64-input /16-output convolution used by the two legacy refinement
// passes. Group output is8x8x16; cooperate on input loads, partition channels.
Texture2DArray<uint4> activations:register(t0);
StructuredBuffer<uint4> weights:register(t1);
StructuredBuffer<int4> biases:register(t2);
StructuredBuffer<int4> slopes:register(t3);
RWTexture2DArray<uint4> outputImage:register(u0);
cbuffer Parameters:register(b0){uint4 c0;uint4 c1;uint4 c2;}
#ifndef CHANNEL_PARTS
#define CHANNEL_PARTS 4
#endif
#ifndef CLAMP_BITS
#define CLAMP_BITS 17
#endif
#if defined(QUAD_CHANNELS) && CHANNEL_PARTS != 4
#error Quad output assembly requires four channel partitions
#endif
groupshared uint4 tile[100];
groupshared uint words[256];
int quantize(int value,int negativeScale){
 value=clamp(value,-(1<<CLAMP_BITS),(1<<CLAMP_BITS)-1);
 uint ps=c2.z&31,ns=(c2.z>>8)&31;
 int p=asint(asuint(max(value,0))*c2.y+(1u<<((ps+31)&31)));
 int n=asint(asuint(min(value,0))*asuint(negativeScale)+(1u<<((ns+31)&31)));
 return clamp((p>>ps)+(n>>ns),-128,127);
}
uint pack4(int4 v){return (asuint(v.x)&255)|((asuint(v.y)&255)<<8)|((asuint(v.z)&255)<<16)|((asuint(v.w)&255)<<24);}
#ifdef MICRO
[RootSignature("DescriptorTable(SRV(t0)), SRV(t1), SRV(t2), SRV(t3), DescriptorTable(UAV(u0)), RootConstants(num32BitConstants=12,b0)")]
#endif
#ifdef QUAD_CHANNELS
[numthreads(16,16,1)]
#else
[numthreads(8,8,CHANNEL_PARTS)]
#endif
void main(uint3 group:SV_GroupID,uint3 rawTid:SV_GroupThreadID){
#ifdef QUAD_CHANNELS
 // SM6.6 defines quad lanes by the low X/Y bits for even 2D groups.
 uint3 tid=uint3(rawTid.x/2,rawTid.y/2,(rawTid.y%2)*2+rawTid.x%2);
#else
 uint3 tid=rawTid;
#endif
 uint2 p=group.xy*8+tid.xy;int4 value[4/CHANNEL_PARTS];
 [unroll]for(uint o=0;o<4/CHANNEL_PARTS;o++)value[o]=biases[group.z*4+tid.z*(4/CHANNEL_PARTS)+o];
 [loop]for(uint ci=0;ci<4;ci++){
  GroupMemoryBarrierWithGroupSync();
  for(uint i=(tid.z*8+tid.y)*8+tid.x;i<100;i+=64*CHANNEL_PARTS){
   int x=(int)(group.x*8+i%10)-1;uint y=group.y*8+i/10;uint4 v=0;
   if(x>=0&&x<(int)c0.z&&y>0&&y<=c0.w)v=activations.Load(int4(x,y,ci,0));tile[i]=v;
  }
  GroupMemoryBarrierWithGroupSync();
  [branch]if(all(p<c1.xy)){
#ifdef PREPARED_FLOAT
   // Every ci chunk has 144 signed-byte products per output channel:
   // sum(abs(products)) <= 144*16384 < 2^24. The float sum is exact;
   // its conversion is added to the original wrapping integer bias.
   float4 partial[4/CHANNEL_PARTS];
   [unroll]for(uint o=0;o<4/CHANNEL_PARTS;o++)partial[o]=0;
#endif
   [unroll]for(uint dy=0;dy<3;dy++)[unroll]for(uint dx=0;dx<3;dx++){
    uint4 input=tile[(tid.y+dy)*10+tid.x+dx];
    [unroll]for(uint pack=0;pack<4;pack++)[unroll]for(uint o=0;o<4/CHANNEL_PARTS;o++){
     uint index=(group.z*4+ci)*144+(tid.z*(4/CHANNEL_PARTS)+o)*36+(dy*3+dx)*4+pack;
#ifdef PREPARED_FLOAT
     float4 a=(float4)(int4((int)(input[pack]<<24)>>24,(int)(input[pack]<<16)>>24,(int)(input[pack]<<8)>>24,(int)input[pack]>>24));
     [unroll]for(uint lane=0;lane<4;lane++){
      float4 w=asfloat(weights[2304+index*4+lane]);
      partial[o][lane]+=dot(a,w);
     }
#else
     uint4 w=weights[index];
     [unroll]for(uint lane=0;lane<4;lane++)value[o][lane]=dot4add_i8packed(input[pack],w[lane],value[o][lane]);
#endif
    }
   }
#ifdef PREPARED_FLOAT
   [unroll]for(uint o=0;o<4/CHANNEL_PARTS;o++)value[o]+=(int4)partial[o];
#endif
  }
 }
#ifdef QUAD_CHANNELS
 int4 s=slopes[group.z*4+tid.z];
 [unroll]for(uint lane=0;lane<4;lane++)value[0][lane]=quantize(value[0][lane],s[lane]);
 uint word=pack4(value[0]);
 // All four lanes participate, including groups crossing the image boundary.
 uint4 assembled=uint4(QuadReadLaneAt(word,0),QuadReadLaneAt(word,1),QuadReadLaneAt(word,2),QuadReadLaneAt(word,3));
 if(tid.z==0&&all(p<c1.xy))outputImage[uint3(p.x,p.y+1,group.z)]=assembled;
#else
 [unroll]for(uint o=0;o<4/CHANNEL_PARTS;o++){
  uint channel=tid.z*(4/CHANNEL_PARTS)+o;int4 s=slopes[group.z*4+channel];
  [unroll]for(uint lane=0;lane<4;lane++)value[o][lane]=quantize(value[o][lane],s[lane]);
  words[channel*64+tid.y*8+tid.x]=pack4(value[o]);
 }
 GroupMemoryBarrierWithGroupSync();
 if(tid.z==0&&all(p<c1.xy)){uint i=tid.y*8+tid.x;outputImage[uint3(p.x,p.y+1,group.z)]=uint4(words[i],words[i+64],words[i+128],words[i+192]);}
#endif
}
