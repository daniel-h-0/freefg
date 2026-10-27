// SPDX-License-Identifier: MIT
// Optional logical texture bounds for generation inside a larger SDK allocation.
// W/H describe this stage's logical input (encoder/row) or output (decoder).
// Each packed delta has the full-grid shrinkage in bits 0..15 and the
// half-grid shrinkage in bits 16..31. Separate deltas cover tiny pyramids whose
// duplicate levels the SDK shares. Preserve the allocation's original padding.
#if FREEFG_VIRTUAL_BOUNDS
#ifndef FREEFG_DIMS_DEFINED
cbuffer FreeFGDimensions : register(b0) {
    int FreeFGW, FreeFGH; uint FreeFGDeltaW, FreeFGDeltaH;
}
#endif
uint2 freefg_bounds(uint2 physical, uint divisor) {
    uint2 packed = uint2(FreeFGDeltaW, FreeFGDeltaH);
    uint2 delta = divisor == 1 ? packed & 65535u : packed >> 16;
    return physical - min(physical, delta);
}
uint4 freefg_load(Texture2DArray<uint4> image, int4 p, uint divisor) {
    uint w,h,layers;image.GetDimensions(w,h,layers);
    return all(uint2(p.xy) < freefg_bounds(uint2(w,h),divisor)) ? image.Load(p) : uint4(0,0,0,0);
}
void freefg_store(RWTexture2DArray<uint4> image, uint3 p, uint divisor, uint4 value) {
    uint w,h,layers;image.GetDimensions(w,h,layers);
    if(all(p.xy < freefg_bounds(uint2(w,h),divisor)))image[p]=value;
}
#define FG_LOAD(image,p,divisor) freefg_load(image,p,divisor)
#define FG_STORE(image,p,divisor,value) freefg_store(image,p,divisor,value)
#define FG_BOUNDS(physical,divisor) freefg_bounds(physical,divisor)
#else
#define FG_LOAD(image,p,divisor) image.Load(p)
#define FG_STORE(image,p,divisor,value) image[p]=(value)
#define FG_BOUNDS(physical,divisor) physical
#endif
