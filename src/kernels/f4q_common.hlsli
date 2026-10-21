// SPDX-License-Identifier: MIT
// F4Q encoder interface (FreeFG 1.1, f4q_enc16.hlsl): resources, input decode and requantisation of the 16 -> 16k int8
// encoder layer of f030948d (wino_rs16.hlsl, the F(2x2) form): 3x3 convolution with "same" padding, then 2x2 max-pool
// (POOL=1) or none, then q = int(float(y) * scale + bias) clamped to [CLAMP_LO, 127] and packed as bytes. Own code:
// every coefficient is read at run time from `model` (src/model_f4q.h); no weight, scale or bias value appears here.
Texture2DArray<uint4> src : register(t0);       // 16 channels per texel (4 words x 4 bytes), slice 0
StructuredBuffer<float4> model : register(t1);  // the F4Q coefficient segment from float4 TBASE (src/model_f4q.h)
StructuredBuffer<float4> scale : register(t2);  // [output channel / 4]
StructuredBuffer<float4> bias : register(t3);   // [output channel / 4]
RWTexture2DArray<uint4> dst : register(u0);

#ifndef POOL
#define POOL 1
#endif
#ifndef CLAMP_LO
#define CLAMP_LO 0
#endif
#ifndef DECODE_OFFSET
#define DECODE_OFFSET 1 // 1: the U-Net input encoding of 1a3b0782 (zero texels read as -128); 0: inner-layer encoding
#endif

// Unsigned code d in [0, 255] of each byte; the signed value is d - 128 (the transforms subtract the offset once).
#if DECODE_OFFSET
uint decode_word(uint w) { return (w + 0x80808080u) ^ 0x80808080u; }
#else
uint decode_word(uint w) { return w ^ 0x80808080u; }
#endif

// Requantise four output channels (q holds integer-valued floats) and pack them into one word.
uint requant4(float4 q, float4 s, float4 b) {
    int4 r = int4(q * s + b);
    return pack_u8(min(max(r, CLAMP_LO), 127));
}
