/* SPDX-License-Identifier: MIT
 * Exact F4 numerator coefficients for the private three-pass U24 experiment.
 * Original model layouts and earlier prepared representations are preserved. */
static UINT model_winograd_channels(UINT bytes){
 if(bytes==451584)return 224;
 if(bytes==36864)return 64;
 model_fail("unsupported Winograd model size");return 0;
}
static UINT model_winograd_size(UINT bytes){UINT n=model_winograd_channels(bytes);
 return n*n*81;}
static void model_winograd_pack(const int8_t*raw,void*destination,UINT bytes){
 static const int g[6][3]={{1,0,0},{-1,-1,-1},{-1,1,-1},{1,2,4},{1,-2,4},{0,0,1}};
 UINT n=model_winograd_channels(bytes),groups=n/16,pack=n==224?8:16,output_packs=pack/4;
 UINT block_bytes=n*36,header=n;
 for(UINT dy=0;dy<6;dy++)for(UINT dx=0;dx<6;dx++)for(UINT ci=0;ci<groups;ci++){
  char*block=(char*)destination+((dy*6+dx)*groups+ci)*block_bytes;
  uint32_t*correction=header?(uint32_t*)block:NULL;
  uint16_t*coefficients=(uint16_t*)(block+header*4);
  for(UINT output=0;output<n;output++){
   int sum=0;
   for(UINT input=0;input<16;input++){
    int value=0;
    for(UINT y=0;y<3;y++)for(UINT x=0;x<3;x++){
     UINT index=(((((((output/pack*groups+ci)*output_packs+(output%pack)/4)*3+y)*3+x)*4+input/4)*4+output%4)*4+input%4);
     value+=g[dy][y]*(int)raw[index]*g[dx][x];
    }
    {
     if(value < -8192 || value > 57343)model_fail("Winograd unsigned coefficient range");
     coefficients[input*n+output]=(uint16_t)(value+8192);
    }
    sum+=value;
   }
   if(correction)correction[output]=(uint32_t)sum*16384u;
  }
 }
}
