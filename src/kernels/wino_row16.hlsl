// SPDX-License-Identifier: MIT
// Exact 1D Winograd F(2,3) int8 3x3 convolution (16->16 or 32->16, signed output), two horizontal pixels x 16 output channels per thread.
Texture2DArray<uint4> src : register(t0);
#ifndef PK16
#define PK16 0 // 1: packed-FP16 MACs (pk16.hlsli); the outputs can differ from the exact form's
#endif
#if PK16
// PK16 (pk16.hlsli): the same buffer read as FP16 quads (byte offset 16 F = quads 2 F, 2 F + 1), so each coefficient pair
// is one 16-bit vector load and the MACs vectorize to v_pk_fma_f16 (vkd3d-proton binds SRVs as SSBOs: the view is a byte
// range, the element type is the shader's).
StructuredBuffer<float16_t4> model : register(t1);
#define MODEL_ZERO_INT int(uint(asuint16(model[2 * (WINO_ZERO)].x)))
#else
StructuredBuffer<float4> model : register(t1);
#define MODEL_ZERO_INT asint(model[WINO_ZERO].x)
#endif
StructuredBuffer<float4> scale : register(t2);
StructuredBuffer<float4> bias : register(t3);
RWTexture2DArray<uint4> dst : register(u0);
#include "virtual_bounds.hlsli"

#ifndef WHALF
#define WHALF 0
#endif
#ifndef ROW_BASE
#define ROW_BASE 1745 // float4 index of U1: 2304-byte model (11520 + 16400) / 16; 4608-byte model: 3489
#endif
#ifndef CIN_SLICES
#define CIN_SLICES 1
#endif
#ifndef CLAMP_LO
#define CLAMP_LO -128
#endif
#ifndef XU1
#define XU1 0 // 1: FP16-pair input transform (needs -enable-16bit-types); same results
#endif
#if PK16
#include "pk16.hlsli"
#endif
#if XU1
// The codes d = (w ^ 0x80808080) bytes (0..255, signed value d - 128) of a source word w as FP16 1024 + d, two
// channels per register: channels (0, 1) for sel 0, (2, 3) for sel 1. The XOR is folded into the exponent bits: for an
// unpacked byte b, (b ^ 0x6480) is the FP16 bit pattern of 1024 + (b ^ 0x80). FP16 holds every integer of magnitude
// <= 2048 exactly. unpack_u8u16 keeps the four values one vector through dxil-spirv (packed FP16 arithmetic).
float16_t2 code_pair(uint w, uint sel) {
    float16_t4 L4 = asfloat16(unpack_u8u16((uint8_t4_packed)w) ^ uint16_t(0x6480));
    return sel ? L4.zw : L4.xy;
}
#endif

[numthreads(4, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID) {
    int x0 = int(id.x) * 2 - 1, y0 = int(id.y) - 1;
    float m[4][16];
    [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint k = 0; k < 16; k++) m[j][k] = 0;
    [unroll] for (uint is = 0; is < CIN_SLICES; is++) {
#if PK16
        float16_t2 c16h[4][8]; // this slice's FP16 chains, output-channel pairs (2l, 2l + 1), units of 2^-8 (U1 * 2^-8 table)
        [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint l = 0; l < 8; l++) c16h[j][l] = float16_t2(0.0, 0.0);
#endif
        [unroll] for (uint q = 0; q < 4; q++) {
#if XU1
            // XU1: the row transform in FP16 pairs, L = 1024 + code (exact): v = (L0 - L2, (L1 - 2304) + L2, L2 - L1,
            // L1 - L3) = (d0 - d2, d1 + d2 - 256, d2 - d1, d1 - d3), the release kernel's values. Every operand and
            // result is an integer of magnitude <= 2048 (|L1 - 2304| <= 1280, |v| <= 255), so each FP16 operation is
            // exact; `precise` keeps the compiler from regrouping sums of two biased values.
            uint wr[3][4];
            [unroll] for (uint r = 0; r < 3; r++) [unroll] for (uint i = 0; i < 4; i++)
                wr[r][i] = FG_LOAD(src,int4(x0 + int(i), y0 + int(r), int(is), 0),1)[q];
            [unroll] for (uint r = 0; r < 3; r++) {
                float16_t2 vh[2][4]; // [sel][j]: sel 0 = channels (4q, 4q + 1), sel 1 = (4q + 2, 4q + 3)
                [unroll] for (uint sel = 0; sel < 2; sel++) {
                    float16_t2 L0 = code_pair(wr[r][0], sel), L1 = code_pair(wr[r][1], sel);
                    float16_t2 L2 = code_pair(wr[r][2], sel), L3 = code_pair(wr[r][3], sel);
                    precise float16_t2 v0 = L0 - L2;
                    precise float16_t2 v1 = (L1 + float16_t2(-2304.0, -2304.0)) + L2;
                    precise float16_t2 v2 = L2 - L1;
                    precise float16_t2 v3 = L1 - L3;
                    vh[sel][0] = v0; vh[sel][1] = v1; vh[sel][2] = v2; vh[sel][3] = v3;
                }
                [unroll] for (uint b = 0; b < 4; b++) {
                    uint c = q * 4 + b;
                    uint base = ROW_BASE + (((is * 16 + c) * 3 + r) * 4) * 4; // U1[chunk][cin][row][j][16 couts]
#if PK16
                    [unroll] for (uint j = 0; j < 4; j++) {
                        float16_t v16 = (b & 1) ? vh[b >> 1][j].y : vh[b >> 1][j].x;
                        float16_t2 a2 = float16_t2(v16, v16);
                        uint F = ROW16_BASE + (base - ROW_BASE) / 2 + j * 2; // FP16 quads 2F .. 2F + 3 = couts 0..15, U1 * 2^-8
                        float16_t4 w0 = model[2 * F], w1 = model[2 * F + 1], w2 = model[2 * F + 2], w3 = model[2 * F + 3];
                        c16h[j][0] = mad(a2, w0.xy, c16h[j][0]); c16h[j][1] = mad(a2, w0.zw, c16h[j][1]);
                        c16h[j][2] = mad(a2, w1.xy, c16h[j][2]); c16h[j][3] = mad(a2, w1.zw, c16h[j][3]);
                        c16h[j][4] = mad(a2, w2.xy, c16h[j][4]); c16h[j][5] = mad(a2, w2.zw, c16h[j][5]);
                        c16h[j][6] = mad(a2, w3.xy, c16h[j][6]); c16h[j][7] = mad(a2, w3.zw, c16h[j][7]);
                    }
#else
                    float v[4];
                    [unroll] for (uint j = 0; j < 4; j++) v[j] = float((b & 1) ? vh[b >> 1][j].y : vh[b >> 1][j].x);
                    [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint kq = 0; kq < 4; kq++) {
#if WHALF
                        uint4 wh = asuint(model[ROW16_BASE + (base - ROW_BASE) / 2 + j * 2 + (kq >> 1)]);
                        uint2 wq = (kq & 1) ? wh.zw : wh.xy;
                        float4 w = float4(f16tof32(wq.x), f16tof32(wq.x >> 16), f16tof32(wq.y), f16tof32(wq.y >> 16));
#else
                        float4 w = model[base + j * 4 + kq];
#endif
                        m[j][kq * 4 + 0] = mad(v[j], w.x, m[j][kq * 4 + 0]); m[j][kq * 4 + 1] = mad(v[j], w.y, m[j][kq * 4 + 1]);
                        m[j][kq * 4 + 2] = mad(v[j], w.z, m[j][kq * 4 + 2]); m[j][kq * 4 + 3] = mad(v[j], w.w, m[j][kq * 4 + 3]);
                    }
#endif
                }
            }
#else
            uint wd[3][4];
            [unroll] for (uint r = 0; r < 3; r++) [unroll] for (uint i = 0; i < 4; i++)
                wd[r][i] = FG_LOAD(src,int4(x0 + int(i), y0 + int(r), int(is), 0),1)[q] ^ 0x80808080u;
            [unroll] for (uint b = 0; b < 4; b++) {
                uint c = q * 4 + b;
                [unroll] for (uint r = 0; r < 3; r++) {
                    float d0 = float((wd[r][0] >> (8 * b)) & 0xffu), d1 = float((wd[r][1] >> (8 * b)) & 0xffu);
                    float d2 = float((wd[r][2] >> (8 * b)) & 0xffu), d3 = float((wd[r][3] >> (8 * b)) & 0xffu);
                    float v[4] = { d0 - d2, d1 + d2 - 256.0, d2 - d1, d1 - d3 };
                    uint base = ROW_BASE + (((is * 16 + c) * 3 + r) * 4) * 4; // U1[chunk][cin][row][j][16 couts]
                    [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint kq = 0; kq < 4; kq++) {
#if WHALF
                        // FP16 copy U1h[chunk][cin][row][j][16 couts as 2 x uint4] (exact: |U1| <= 384)
                        uint4 wh = asuint(model[ROW16_BASE + (base - ROW_BASE) / 2 + j * 2 + (kq >> 1)]);
                        uint2 wq = (kq & 1) ? wh.zw : wh.xy;
                        float4 w = float4(f16tof32(wq.x), f16tof32(wq.x >> 16), f16tof32(wq.y), f16tof32(wq.y >> 16));
#else
                        float4 w = model[base + j * 4 + kq];
#endif
                        m[j][kq * 4 + 0] = mad(v[j], w.x, m[j][kq * 4 + 0]); m[j][kq * 4 + 1] = mad(v[j], w.y, m[j][kq * 4 + 1]);
                        m[j][kq * 4 + 2] = mad(v[j], w.z, m[j][kq * 4 + 2]); m[j][kq * 4 + 3] = mad(v[j], w.w, m[j][kq * 4 + 3]);
                    }
                }
            }
#endif
        }
#if PK16
        [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint l = 0; l < 8; l++) { // FP32, exact (integers < 2^24)
            m[j][2 * l] = mad(float(c16h[j][l].x), 256.0, m[j][2 * l]); m[j][2 * l + 1] = mad(float(c16h[j][l].y), 256.0, m[j][2 * l + 1]);
        }
#endif
    }
    uint4 o0, o1;
    [unroll] for (uint o = 0; o < 4; o++) {
        float4 s = scale[o], b = bias[o];
        int4 ya, yb;
        [unroll] for (uint l = 0; l < 4; l++) {
            uint k = o * 4 + l;
            int a0 = int(m[0][k]), a1 = int(m[1][k]), a2 = int(m[2][k]), a3 = int(m[3][k]);
#if PK16
            ya[l] = pk16_shr(a0 + a1 + a2, 1); yb[l] = pk16_shr(a1 - a2 - a3, 1);
#else
            ya[l] = (a0 + a1 + a2) >> 1; yb[l] = (a1 - a2 - a3) >> 1;
#endif
        }
        o0[o] = pack_u8(min(max(int4(float4(ya) * s + b), CLAMP_LO), 127));
        o1[o] = pack_u8(min(max(int4(float4(yb) * s + b), CLAMP_LO), 127));
    }
    FG_STORE(dst,uint3(id.x * 2, id.y, 0),1,o0);
    FG_STORE(dst,uint3(id.x * 2 + 1, id.y, 0),1,o1);
}
