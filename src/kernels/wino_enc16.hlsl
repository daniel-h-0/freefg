// SPDX-License-Identifier: MIT
// Exact Winograd F(2x2,3x3) int8 3x3 convolution of 16-channel texture slices, with optional 2x2 max-pool, per-channel scale/bias, clamp and pack.
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

#ifndef WHALF
#define WHALF 0 // coefficients as FP16 pairs from a segment at WINO16_BASE (float4 index)
#endif
#ifndef WINO_BASE
#define WINO_BASE 720 // float4 index after 2304 raw bytes + 2304 floats
#endif

#ifndef DECODE_OFFSET
#define DECODE_OFFSET 1 // 1: s = int8(byte(w + 0x80808080)) (U-Net input); 0: s = int8(byte(w)) (inner layers)
#endif
#ifndef SLICES
#define SLICES 1        // output texture slices of 16 channels; slice = SV_GroupID.z
#endif
#ifndef CIN_SLICES
#define CIN_SLICES 1    // input texture slices of 16 channels; raw chunk (slice*CIN_SLICES+is) is 2304 B
#endif
#ifndef XU1
#define XU1 0 // 1: FP16-pair input transform (needs -enable-16bit-types, PHASED); same results
#endif
#if DECODE_OFFSET
uint decode_word(uint w) { return (w + 0x80808080u) ^ 0x80808080u; }
#else
uint decode_word(uint w) { return w ^ 0x80808080u; }
#endif
#if XU1
// The codes d = decode_word(w) bytes (0..255, signed value d - 128) as FP16 1024 + d, two channels per register:
// channels (0, 1) for sel 0, (2, 3) for sel 1. The decode's final XOR is folded into the exponent bits: for an
// unpacked byte b, (b ^ 0x6480) is the FP16 bit pattern of 1024 + (b ^ 0x80). FP16 holds every integer of magnitude
// <= 2048 exactly. unpack_u8u16 keeps the four values one vector through dxil-spirv (packed FP16 arithmetic).
#if DECODE_OFFSET
uint decode_raw(uint w) { return w + 0x80808080u; }
#else
uint decode_raw(uint w) { return w; }
#endif
float16_t2 code_pair(uint raw, uint sel) {
    float16_t4 L4 = asfloat16(unpack_u8u16((uint8_t4_packed)raw) ^ uint16_t(0x6480));
    return sel ? L4.zw : L4.xy;
}
#endif
uint4 load_patch(int x, int y) { uint4 w = src.Load(int4(x, y, 0, 0)); return uint4(decode_word(w.x), decode_word(w.y), decode_word(w.z), decode_word(w.w)); }

#ifndef WINO_ZERO
#define WINO_ZERO (WINO_BASE + 1024 * SLICES * CIN_SLICES) // one zero float4 after the transformed weights
#endif
#ifndef PHASED
#define PHASED 0
#endif
#ifndef FP16T
#define FP16T 0
#endif
#ifndef GX
#define GX 16
#endif
#ifndef GY
#define GY 8
#endif
#ifndef NOPOOL
#define NOPOOL 0
#endif
#ifndef FLOAT_ALL
#define FLOAT_ALL 0
#endif
#if PK16
#include "pk16.hlsli"
#endif
#ifndef KSPLIT
#define KSPLIT 1 // split-K (NOPOOL multi-slice): waves per channel half, each summing CIN_SLICES / KSPLIT input slices
#endif
#if KSPLIT > 1 && !(NOPOOL && CIN_SLICES > 1 && CIN_SLICES % KSPLIT == 0)
#error KSPLIT needs a NOPOOL multi-slice layer whose input slices divide evenly
#endif
#ifndef CLAMP_LO
#define CLAMP_LO 0 // -128 for signed output heads (clamp to [-128, 127])
#endif
#if XU1 && (!PHASED || FP16T)
#error XU1 needs PHASED and replaces FP16T
#endif
#if NOPOOL
groupshared uint4 swap4[GX * GY * 2];
#if KSPLIT > 1
groupshared uint4 red[(KSPLIT - 1) * 2 * GX * GY * 8]; // int32 partials of waves ks > 0, [ks-1][h][tile][8 x int4]
#endif
#else
groupshared uint2 upper[GX * GY];
#endif

// Group GXxGYx2: z selects the output-channel half. Each z slice must fill whole waves
// (GX*GY a multiple of the wave size) so h is truly wave-uniform.
#if KSPLIT > 1
[numthreads(GX, GY, 2 * KSPLIT)]
#else
[numthreads(GX, GY, 2)]
#endif
#if SLICES > 1
void CSMain(uint3 id : SV_DispatchThreadID, uint3 gt : SV_GroupThreadID, uint3 gid : SV_GroupID) {
    uint slice = gid.z;
#else
void CSMain(uint3 id : SV_DispatchThreadID, uint3 gt : SV_GroupThreadID) {
    const uint slice = 0;
#endif
#if KSPLIT > 1
    uint gz = WaveReadLaneFirst(gt.z), h = gz & 1, ks = gz >> 1;
#else
    uint h = WaveReadLaneFirst(gt.z);
#endif
    int x0 = int(id.x) * 2 - 1, y0 = int(id.y) * 2 - 1;
#if PHASED
    // Per-word phases: only one 32-bit word per texel is live. An opaque zero from the
    // model segment keeps the four phases' loads distinct (no CSE back into uint4 loads).
    int zero = MODEL_ZERO_INT;
    uint patch[4][4];
#else
    uint4 patch[4][4];
    [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++) patch[j][i] = load_patch(x0 + int(i), y0 + int(j));
#endif
#if CIN_SLICES > 1 && FLOAT_ALL
    // Owner-proven for the bound model: 512 * max_{p,k} sum_{all cin} |U| < 2^24, so the whole
    // multi-slice sum is exact in FP32 and a single inverse transform follows the slice loop.
    float m[16][8];
    [unroll] for (uint p = 0; p < 16; p++) [unroll] for (uint k = 0; k < 8; k++) m[p][k] = 0;
#if KSPLIT > 1
    [loop] for (uint is = ks * (CIN_SLICES / KSPLIT); is < (ks + 1) * (CIN_SLICES / KSPLIT); is++) {
#else
    [loop] for (uint is = 0; is < CIN_SLICES; is++) {
#endif
#elif CIN_SLICES > 1
    // Each 16-channel chunk is exact in FP32; chunks meet in int32 after the inverse transform.
    int acc[4][8];
    [unroll] for (uint a = 0; a < 4; a++) [unroll] for (uint k = 0; k < 8; k++) acc[a][k] = 0;
#if KSPLIT > 1
    [loop] for (uint is = ks * (CIN_SLICES / KSPLIT); is < (ks + 1) * (CIN_SLICES / KSPLIT); is++) {
#else
    [loop] for (uint is = 0; is < CIN_SLICES; is++) {
#endif
#else
    const uint is = 0;
#endif
#if !(CIN_SLICES > 1 && FLOAT_ALL)
    float m[16][8];
    [unroll] for (uint p = 0; p < 16; p++) [unroll] for (uint k = 0; k < 8; k++) m[p][k] = 0;
#endif
#if PK16
    float16_t2 pk[16][4]; // [position][output-channel pair (2j, 2j + 1)]: this input slice's FP16 chains, units of 2^-8
    [unroll] for (uint p = 0; p < 16; p++) [unroll] for (uint j = 0; j < 4; j++) pk[p][j] = float16_t2(0.0, 0.0);
#endif
#if XU1
    // XU1: the transform in FP16 pairs, L = 1024 + code (exact), signed values s = code - 128:
    //   t0 = L0 - L2 = s0 - s2, t1 = (L1 - 2304) + L2 = s1 + s2, t2 = L2 - L1 = s2 - s1, t3 = L1 - L3 = s1 - s3,
    // then the same column transform: v = B^T s B, the release kernel's values (its +512 offset at v[1][1] is not
    // there to remove). Every operand and result is an integer of magnitude <= 2048 (|L1 - 2304| <= 1280,
    // |t| <= 256, |v| <= 512), so each FP16 operation is exact. `precise` keeps the compiler from regrouping sums of
    // two biased values (L + L' is not exact in FP16).
    [unroll] for (uint q = 0; q < 4; q++) {
        int xz = x0 + zero * int(q);
        [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++)
#if CIN_SLICES > 1
            patch[j][i] = decode_raw(src.Load(int4(xz + int(i), y0 + int(j), int(is), 0))[q]);
#else
            patch[j][i] = decode_raw(src.Load(int4(xz + int(i), y0 + int(j), 0, 0))[q]);
#endif
        float16_t2 vh[2][16]; // [sel][position]: sel 0 = channels (4q, 4q + 1), sel 1 = (4q + 2, 4q + 3)
        [unroll] for (uint sel = 0; sel < 2; sel++) {
            precise float16_t2 t[4][4];
            precise float16_t2 v[4][4];
            [unroll] for (uint i = 0; i < 4; i++) {
                float16_t2 L0 = code_pair(patch[0][i], sel), L1 = code_pair(patch[1][i], sel);
                float16_t2 L2 = code_pair(patch[2][i], sel), L3 = code_pair(patch[3][i], sel);
                t[0][i] = L0 - L2; t[1][i] = (L1 + float16_t2(-2304.0, -2304.0)) + L2;
                t[2][i] = L2 - L1; t[3][i] = L1 - L3;
            }
            [unroll] for (uint j = 0; j < 4; j++) {
                v[j][0] = t[j][0] - t[j][2]; v[j][1] = t[j][1] + t[j][2];
                v[j][2] = t[j][2] - t[j][1]; v[j][3] = t[j][1] - t[j][3];
            }
            [unroll] for (uint p = 0; p < 16; p++) vh[sel][p] = v[p >> 2][p & 3];
        }
        [unroll] for (uint cc = 0; cc < 4; cc++) {
            uint c = q * 4 + cc;
#if CIN_SLICES > 1
            uint base = WINO_BASE + ((slice * CIN_SLICES + is) * 2 + h) * 512 + c * 32; // U[raw chunk][half][cin][p][k]
#else
            uint base = WINO_BASE + slice * 1024 + (h * 16 + c) * 32;
#endif
            [unroll] for (uint p = 0; p < 16; p++) {
#if PK16
                float16_t4 whl = model[2 * (WINO16_BASE + (base - WINO_BASE) / 2 + p)], whu = model[2 * (WINO16_BASE + (base - WINO_BASE) / 2 + p) + 1]; // FP16 pairs U' * 2^-8
                float16_t a16 = (cc & 1) ? vh[cc >> 1][p].y : vh[cc >> 1][p].x;
                float16_t2 a2 = float16_t2(a16, a16);
                pk[p][0] = mad(a2, whl.xy, pk[p][0]); pk[p][1] = mad(a2, whl.zw, pk[p][1]);
                pk[p][2] = mad(a2, whu.xy, pk[p][2]); pk[p][3] = mad(a2, whu.zw, pk[p][3]);
#else
#if WHALF
                uint4 wh = asuint(model[WINO16_BASE + (base - WINO_BASE) / 2 + p]); // FP16 pairs, exact (|U| <= 1152)
                float4 w0 = float4(f16tof32(wh.x), f16tof32(wh.x >> 16), f16tof32(wh.y), f16tof32(wh.y >> 16));
                float4 w1 = float4(f16tof32(wh.z), f16tof32(wh.z >> 16), f16tof32(wh.w), f16tof32(wh.w >> 16));
#else
                float4 w0 = model[base + p * 2], w1 = model[base + p * 2 + 1];
#endif
                float a = float((cc & 1) ? vh[cc >> 1][p].y : vh[cc >> 1][p].x);
                m[p][0] = mad(a, w0.x, m[p][0]); m[p][1] = mad(a, w0.y, m[p][1]);
                m[p][2] = mad(a, w0.z, m[p][2]); m[p][3] = mad(a, w0.w, m[p][3]);
                m[p][4] = mad(a, w1.x, m[p][4]); m[p][5] = mad(a, w1.y, m[p][5]);
                m[p][6] = mad(a, w1.z, m[p][6]); m[p][7] = mad(a, w1.w, m[p][7]);
#endif
            }
        }
    }
#if PK16
    // Flush this slice's chains: value * 2^8 (an integer), added in FP32 (exact: every partial sum of the
    // slice results is an integer below 2^24, the bound the FLOAT_ALL kernels' owner proves with a margin).
    [unroll] for (uint p = 0; p < 16; p++) [unroll] for (uint j = 0; j < 4; j++) {
        m[p][2 * j] = mad(float(pk[p][j].x), 256.0, m[p][2 * j]); m[p][2 * j + 1] = mad(float(pk[p][j].y), 256.0, m[p][2 * j + 1]);
    }
#endif
#else
    [unroll] for (uint c = 0; c < 16; c++) {
#if FP16T
        // Exact in FP16: u in [0,255], |t| <= 510, |v| <= 1020 (< 2048). FP32 accumulation unchanged.
        float16_t d[4][4], t[4][4], v[4][4];
#else
        float d[4][4], t[4][4], v[4][4];
#endif
#if PHASED
        if ((c & 3) == 0) {
            int xz = x0 + zero * int(c >> 2);
            [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++)
#if CIN_SLICES > 1
                patch[j][i] = decode_word(src.Load(int4(xz + int(i), y0 + int(j), int(is), 0))[c >> 2]);
#else
                patch[j][i] = decode_word(src.Load(int4(xz + int(i), y0 + int(j), 0, 0))[c >> 2]);
#endif
        }
        [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++)
#if FP16T
            d[j][i] = float16_t((patch[j][i] >> (8 * (c & 3))) & 0xffu);
#else
            d[j][i] = float((patch[j][i] >> (8 * (c & 3))) & 0xffu);
#endif
#else
        [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++)
            d[j][i] = float((patch[j][i][c >> 2] >> (8 * (c & 3))) & 0xffu);
#endif
        [unroll] for (uint i = 0; i < 4; i++) {
            t[0][i] = d[0][i] - d[2][i]; t[1][i] = d[1][i] + d[2][i];
            t[2][i] = d[2][i] - d[1][i]; t[3][i] = d[1][i] - d[3][i];
        }
        [unroll] for (uint j = 0; j < 4; j++) {
            v[j][0] = t[j][0] - t[j][2]; v[j][1] = t[j][1] + t[j][2];
            v[j][2] = t[j][2] - t[j][1]; v[j][3] = t[j][1] - t[j][3];
        }
#if FP16T
        v[1][1] -= float16_t(512.0);
#else
        v[1][1] -= 512.0;
#endif
#if CIN_SLICES > 1
        uint base = WINO_BASE + ((slice * CIN_SLICES + is) * 2 + h) * 512 + c * 32; // U[raw chunk][half][cin][p][k]
#else
        uint base = WINO_BASE + slice * 1024 + (h * 16 + c) * 32;
#endif
        [unroll] for (uint p = 0; p < 16; p++) {
#if WHALF
            uint4 wh = asuint(model[WINO16_BASE + (base - WINO_BASE) / 2 + p]); // FP16 pairs, exact (|U| <= 1152)
            float4 w0 = float4(f16tof32(wh.x), f16tof32(wh.x >> 16), f16tof32(wh.y), f16tof32(wh.y >> 16));
            float4 w1 = float4(f16tof32(wh.z), f16tof32(wh.z >> 16), f16tof32(wh.w), f16tof32(wh.w >> 16));
#else
            float4 w0 = model[base + p * 2], w1 = model[base + p * 2 + 1];
#endif
            float a = float(v[p >> 2][p & 3]);
            m[p][0] = mad(a, w0.x, m[p][0]); m[p][1] = mad(a, w0.y, m[p][1]);
            m[p][2] = mad(a, w0.z, m[p][2]); m[p][3] = mad(a, w0.w, m[p][3]);
            m[p][4] = mad(a, w1.x, m[p][4]); m[p][5] = mad(a, w1.y, m[p][5]);
            m[p][6] = mad(a, w1.z, m[p][6]); m[p][7] = mad(a, w1.w, m[p][7]);
        }
    }
#endif
#if CIN_SLICES > 1 && FLOAT_ALL
    }
    int acc[4][8];
    [unroll] for (uint k = 0; k < 8; k++) {
        int mi[16];
        [unroll] for (uint p = 0; p < 16; p++) mi[p] = int(m[p][k]);
        int r[2][4];
        [unroll] for (uint i = 0; i < 4; i++) {
            r[0][i] = mi[i] + mi[4 + i] + mi[8 + i];
            r[1][i] = mi[4 + i] - mi[8 + i] - mi[12 + i];
        }
        acc[0][k] = r[0][0] + r[0][1] + r[0][2]; acc[1][k] = r[0][1] - r[0][2] - r[0][3];
        acc[2][k] = r[1][0] + r[1][1] + r[1][2]; acc[3][k] = r[1][1] - r[1][2] - r[1][3];
    }
#endif
#if CIN_SLICES > 1 && !FLOAT_ALL
    [unroll] for (uint k = 0; k < 8; k++) {
        int mi[16];
        [unroll] for (uint p = 0; p < 16; p++) mi[p] = int(m[p][k]);
        int r[2][4];
        [unroll] for (uint i = 0; i < 4; i++) {
            r[0][i] = mi[i] + mi[4 + i] + mi[8 + i];
            r[1][i] = mi[4 + i] - mi[8 + i] - mi[12 + i];
        }
        acc[0][k] += r[0][0] + r[0][1] + r[0][2]; acc[1][k] += r[0][1] - r[0][2] - r[0][3];
        acc[2][k] += r[1][0] + r[1][1] + r[1][2]; acc[3][k] += r[1][1] - r[1][2] - r[1][3];
    }
    }
#endif
#if KSPLIT > 1
    // Split-K partials (exact int32, 4x the conv) meet in LDS; wave ks == 0 of each half finishes.
    uint tile = gt.y * GX + gt.x;
    if (ks > 0) [unroll] for (uint q = 0; q < 8; q++)
        red[(((ks - 1) * 2 + h) * GX * GY + tile) * 8 + q] = asuint(int4(acc[q >> 1][(q & 1) * 4], acc[q >> 1][(q & 1) * 4 + 1], acc[q >> 1][(q & 1) * 4 + 2], acc[q >> 1][(q & 1) * 4 + 3]));
    GroupMemoryBarrierWithGroupSync();
    if (ks == 0) [unroll] for (uint o = 0; o < KSPLIT - 1; o++) [unroll] for (uint q = 0; q < 8; q++) {
        int4 r4 = asint(red[((o * 2 + h) * GX * GY + tile) * 8 + q]);
        acc[q >> 1][(q & 1) * 4] += r4.x; acc[q >> 1][(q & 1) * 4 + 1] += r4.y;
        acc[q >> 1][(q & 1) * 4 + 2] += r4.z; acc[q >> 1][(q & 1) * 4 + 3] += r4.w;
    }
#endif
#if CIN_SLICES > 1
#if NOPOOL
    int y[4][8]; // acc order is pixel (0,0) (1,0) (0,1) (1,1)
#if PK16
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) y[px][k] = pk16_shr(acc[px][k], 2);
#else
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) y[px][k] = acc[px][k] >> 2;
#endif
#else
    int q[8];
#if PK16
    [unroll] for (uint k = 0; k < 8; k++) q[k] = pk16_shr(max(max(acc[0][k], acc[1][k]), max(acc[2][k], acc[3][k])), 2);
#else
    [unroll] for (uint k = 0; k < 8; k++) q[k] = max(max(acc[0][k], acc[1][k]), max(acc[2][k], acc[3][k])) >> 2;
#endif
#endif
#elif NOPOOL
    // Plain conv: the 2x2 tile's four pixels are all outputs.
    int y[4][8]; // [pixel (0,0) (1,0) (0,1) (1,1)][k]
    [unroll] for (uint k = 0; k < 8; k++) {
        int mi[16];
        [unroll] for (uint p = 0; p < 16; p++) mi[p] = int(m[p][k]);
        int r[2][4];
        [unroll] for (uint i = 0; i < 4; i++) {
            r[0][i] = mi[i] + mi[4 + i] + mi[8 + i];
            r[1][i] = mi[4 + i] - mi[8 + i] - mi[12 + i];
        }
#if PK16
        y[0][k] = pk16_shr(r[0][0] + r[0][1] + r[0][2], 2); y[1][k] = pk16_shr(r[0][1] - r[0][2] - r[0][3], 2);
        y[2][k] = pk16_shr(r[1][0] + r[1][1] + r[1][2], 2); y[3][k] = pk16_shr(r[1][1] - r[1][2] - r[1][3], 2);
#else
        y[0][k] = (r[0][0] + r[0][1] + r[0][2]) >> 2; y[1][k] = (r[0][1] - r[0][2] - r[0][3]) >> 2;
        y[2][k] = (r[1][0] + r[1][1] + r[1][2]) >> 2; y[3][k] = (r[1][1] - r[1][2] - r[1][3]) >> 2;
#endif
    }
#else
    int q[8];
    [unroll] for (uint k = 0; k < 8; k++) {
        int mi[16];
        [unroll] for (uint p = 0; p < 16; p++) mi[p] = int(m[p][k]);
        int r[2][4];
        [unroll] for (uint i = 0; i < 4; i++) {
            r[0][i] = mi[i] + mi[4 + i] + mi[8 + i];
            r[1][i] = mi[4 + i] - mi[8 + i] - mi[12 + i];
        }
        int y00 = r[0][0] + r[0][1] + r[0][2], y01 = r[0][1] - r[0][2] - r[0][3];
        int y10 = r[1][0] + r[1][1] + r[1][2], y11 = r[1][1] - r[1][2] - r[1][3];
#if PK16
        q[k] = pk16_shr(max(max(y00, y01), max(y10, y11)), 2);
#else
        q[k] = max(max(y00, y01), max(y10, y11)) >> 2;
#endif
    }
#endif
#if NOPOOL
    uint2 pw[4];
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint o = 0; o < 2; o++) {
        float4 s = scale[slice * 4 + h * 2 + o], b = bias[slice * 4 + h * 2 + o];
        int4 r4 = int4(float4(y[px][o * 4], y[px][o * 4 + 1], y[px][o * 4 + 2], y[px][o * 4 + 3]) * s + b);
        pw[px][o] = pack_u8(min(max(r4, CLAMP_LO), 127));
    }
    // Halves exchange words: half 0 stores the top pixel row, half 1 the bottom row.
    uint slot = (gt.y * GX + gt.x) * 2;
#if KSPLIT > 1
    if (ks == 0) { if (h == 0) swap4[slot] = uint4(pw[2], pw[3]); else swap4[slot + 1] = uint4(pw[0], pw[1]); }
    GroupMemoryBarrierWithGroupSync();
    if (ks != 0) return;
#else
    if (h == 0) swap4[slot] = uint4(pw[2], pw[3]); else swap4[slot + 1] = uint4(pw[0], pw[1]);
    GroupMemoryBarrierWithGroupSync();
#endif
    uint ox = id.x * 2, oy = id.y * 2;
    if (h == 0) { uint4 o = swap4[slot + 1]; dst[uint3(ox, oy, slice)] = uint4(pw[0], o.xy); dst[uint3(ox + 1, oy, slice)] = uint4(pw[1], o.zw); }
    else        { uint4 o = swap4[slot];     dst[uint3(ox, oy + 1, slice)] = uint4(o.xy, pw[2]); dst[uint3(ox + 1, oy + 1, slice)] = uint4(o.zw, pw[3]); }
}
#else
    uint2 words;
    [unroll] for (uint o = 0; o < 2; o++) {
        float4 s = scale[slice * 4 + h * 2 + o], b = bias[slice * 4 + h * 2 + o];
        int4 r4 = int4(float4(q[o * 4], q[o * 4 + 1], q[o * 4 + 2], q[o * 4 + 3]) * s + b);
        r4 = min(max(r4, 0), 127);
        words[o] = pack_u8(r4);
    }
    uint slot = gt.y * GX + gt.x;
    if (h == 1) upper[slot] = words;
    GroupMemoryBarrierWithGroupSync();
    if (h == 0) dst[uint3(id.xy, slice)] = uint4(words, upper[slot]);
}
#endif
