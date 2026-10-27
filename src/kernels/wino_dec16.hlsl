// SPDX-License-Identifier: MIT
// Exact Winograd F(2x2,3x3) int8 3x3 convolution of a skip input plus a 2x-upsampled low-resolution input (decoder stage), scale/bias, clamp and pack.
Texture2DArray<uint4> low : register(t0);
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
Texture2DArray<uint4> skip : register(t4);
RWTexture2DArray<uint4> dst : register(u0);
cbuffer Dims : register(b0) { int W; int H;
#if FREEFG_VIRTUAL_BOUNDS
 uint FreeFGDeltaW; uint FreeFGDeltaH;
#endif
};
#define FREEFG_DIMS_DEFINED 1
#define FreeFGW W
#define FreeFGH H
#include "virtual_bounds.hlsli"

#ifndef WHALF
#define WHALF 0 // coefficients as FP16 pairs from a segment at WINO16_BASE (float4 index)
#endif
#ifndef XU1
#define XU1 0 // 1: FP16-pair input transform (needs -enable-16bit-types); same results
#endif
#ifndef WINO_BASE
#define WINO_BASE 720
#endif
#ifndef SLICES
#define SLICES 1      // output slices of 16 channels (SV_GroupID.z)
#endif
#ifndef FLOAT_ALL
#define FLOAT_ALL 0
#endif
#ifndef FILL_BY_WORD
#define FILL_BY_WORD 0
#endif
#ifndef CIN_SLICES
#define CIN_SLICES 1  // input slices of 16 channels (low and skip share the slice index)
#endif
#if PK16
#include "pk16.hlsli"
#endif
#define WINO_ZERO (WINO_BASE + 1024 * SLICES * CIN_SLICES)
#ifndef TILE_H
#define TILE_H 16 // output tile 16 x TILE_H pixels per group
#endif
#ifndef TW
#define TW 16 // output tile width; with TILE_H must tile the replaced dispatch's group footprint exactly
#endif
#define LW (TW + 2)
#define LH (TILE_H + 2)
#define GX (TW / 2)
#define GY (TILE_H / 2)

groupshared uint4 tile[LH * LW];
groupshared uint4 swap[GX * GY * 2];

#ifndef UP_SHIFT
#define UP_SHIFT 0 // 1: truncating /16 as (s + (uint(s) >> 28)) >> 4 (|s| <= 2048), no v_mul_lo_u32 by sign(s)
#endif
int4 up(int4 a, int4 b, int4 c, int4 d) {
#if UP_SHIFT
    int4 s = 9 * a + 3 * (b + c) + d;
    return (s + int4(uint4(s) >> 28)) >> 4; // s < 0: + 15 then floor = trunc; s >= 0: floor = trunc
#else
    return (9 * a + 3 * (b + c) + d) / 16;
#endif
}
uint fill_word(int4 s, int4 u) { return pack_u8(clamp(s + u, 0, 127)); }
#if XU1
// The codes d = (w ^ 0x80808080) bytes (0..255, signed value d - 128) of a tile word w as FP16 1024 + d, two channels
// per register: channels (0, 1) for sel 0, (2, 3) for sel 1. The XOR is folded into the exponent bits: for an unpacked
// byte b, (b ^ 0x6480) is the FP16 bit pattern of 1024 + (b ^ 0x80). FP16 holds every integer of magnitude <= 2048
// exactly. unpack_u8u16 keeps the four values one vector through dxil-spirv (packed FP16 arithmetic).
float16_t2 code_pair(uint w, uint sel) {
    float16_t4 L4 = asfloat16(unpack_u8u16((uint8_t4_packed)w) ^ uint16_t(0x6480));
    return sel ? L4.zw : L4.xy;
}
#endif

[numthreads(GX, GY, 2)]
void CSMain(uint3 gid : SV_GroupID, uint3 gt : SV_GroupThreadID) {
    uint h = WaveReadLaneFirst(gt.z);
    int x0 = int(gid.x) * TW, y0 = int(gid.y) * TILE_H;
#if CIN_SLICES > 1
    uint slice = gid.z;
    uint r0 = gt.y * 2, c0 = gt.x * 2;
#if FLOAT_ALL
    // Owner-proven for the bound model: 512 * max_{p,k} sum_{all cin} |U| < 2^24 (whole sum exact in FP32).
    float m[16][8];
    [unroll] for (uint p = 0; p < 16; p++) [unroll] for (uint k = 0; k < 8; k++) m[p][k] = 0;
#else
    int acc[4][8];
    [unroll] for (uint a = 0; a < 4; a++) [unroll] for (uint k = 0; k < 8; k++) acc[a][k] = 0;
#endif
    [loop] for (uint is = 0; is < CIN_SLICES; is++) {
    if (is) GroupMemoryBarrierWithGroupSync(); // every wave finished reading the previous slice
#define SLICE_ARG int(is)
#else
#define SLICE_ARG 0
#endif
    // ---- fill: low-res positions (i, j) cover LDS columns 2i, 2i+1 and rows 2j, 2j+1.
    uint lin = (gt.z * GY + gt.y) * GX + gt.x;
    for (uint f = lin; f < (TW / 2 + 1) * (TILE_H / 2 + 1); f += GX * GY * 2) {
        int i = int(f % (TW / 2 + 1)), j = int(f / (TW / 2 + 1));
        int lx = i + x0 / 2, ly = j + y0 / 2;
#if FILL_BY_WORD
        // One 32-bit word (4 channels) of each of the 8 source texels at a time: 8 live dwords instead of
        // 8 uint4, which keeps the fill under the conv's register budget. The opaque zero keeps the four
        // word phases' loads distinct (no CSE back into uint4 loads).
        int fz = MODEL_ZERO_INT;
        int Xm = 2 * lx - 1, Xp = 2 * lx, Ym = 2 * ly - 1, Yp = 2 * ly;
        bool xm = Xm < 0 || Xm > W - 1, xp = Xp < 0 || Xp > W - 1, ym = Ym < 0 || Ym > H - 1, yp = Yp < 0 || Yp > H - 1;
        [unroll] for (uint q = 0; q < 4; q++) {
            int zq = fz * int(q);
            int4 a = unpack_s8s32(FG_LOAD(low,int4(lx - 1 + zq, ly - 1, SLICE_ARG, 0),2)[q]), b = unpack_s8s32(FG_LOAD(low,int4(lx + zq, ly - 1, SLICE_ARG, 0),2)[q]);
            int4 c = unpack_s8s32(FG_LOAD(low,int4(lx - 1 + zq, ly, SLICE_ARG, 0),2)[q]), d = unpack_s8s32(FG_LOAD(low,int4(lx + zq, ly, SLICE_ARG, 0),2)[q]);
            uint wtl = fill_word(unpack_s8s32(FG_LOAD(skip,int4(Xm + zq, Ym, SLICE_ARG, 0),1)[q]), up(a, b, c, d));
            uint wtr = fill_word(unpack_s8s32(FG_LOAD(skip,int4(Xp + zq, Ym, SLICE_ARG, 0),1)[q]), up(b, d, a, c));
            uint wbl = fill_word(unpack_s8s32(FG_LOAD(skip,int4(Xm + zq, Yp, SLICE_ARG, 0),1)[q]), up(c, a, d, b));
            uint wbr = fill_word(unpack_s8s32(FG_LOAD(skip,int4(Xp + zq, Yp, SLICE_ARG, 0),1)[q]), up(d, c, b, a));
            tile[(2 * j) * LW + 2 * i][q] = (xm || ym) ? 0 : wtl;
            tile[(2 * j) * LW + 2 * i + 1][q] = (xp || ym) ? 0 : wtr;
            tile[(2 * j + 1) * LW + 2 * i][q] = (xm || yp) ? 0 : wbl;
            tile[(2 * j + 1) * LW + 2 * i + 1][q] = (xp || yp) ? 0 : wbr;
        }
#else
        uint4 L00 = FG_LOAD(low,int4(lx - 1, ly - 1, SLICE_ARG, 0),2), L10 = FG_LOAD(low,int4(lx, ly - 1, SLICE_ARG, 0),2);
        uint4 L01 = FG_LOAD(low,int4(lx - 1, ly, SLICE_ARG, 0),2), L11 = FG_LOAD(low,int4(lx, ly, SLICE_ARG, 0),2);
        int Xm = 2 * lx - 1, Xp = 2 * lx, Ym = 2 * ly - 1, Yp = 2 * ly;
        uint4 Smm = FG_LOAD(skip,int4(Xm, Ym, SLICE_ARG, 0),1), Spm = FG_LOAD(skip,int4(Xp, Ym, SLICE_ARG, 0),1);
        uint4 Smp = FG_LOAD(skip,int4(Xm, Yp, SLICE_ARG, 0),1), Spp = FG_LOAD(skip,int4(Xp, Yp, SLICE_ARG, 0),1);
        uint4 tl, tr, bl, br;
        [unroll] for (uint q = 0; q < 4; q++) {
            int4 a = unpack_s8s32(L00[q]), b = unpack_s8s32(L10[q]), c = unpack_s8s32(L01[q]), d = unpack_s8s32(L11[q]);
            tl[q] = fill_word(unpack_s8s32(Smm[q]), up(a, b, c, d));
            tr[q] = fill_word(unpack_s8s32(Spm[q]), up(b, d, a, c));
            bl[q] = fill_word(unpack_s8s32(Smp[q]), up(c, a, d, b));
            br[q] = fill_word(unpack_s8s32(Spp[q]), up(d, c, b, a));
        }
        bool xm = Xm < 0 || Xm > W - 1, xp = Xp < 0 || Xp > W - 1, ym = Ym < 0 || Ym > H - 1, yp = Yp < 0 || Yp > H - 1;
        tile[(2 * j) * LW + 2 * i] = (xm || ym) ? 0 : tl;
        tile[(2 * j) * LW + 2 * i + 1] = (xp || ym) ? 0 : tr;
        tile[(2 * j + 1) * LW + 2 * i] = (xm || yp) ? 0 : bl;
        tile[(2 * j + 1) * LW + 2 * i + 1] = (xp || yp) ? 0 : br;
#endif
    }
    GroupMemoryBarrierWithGroupSync();
    // ---- conv: one 2x2 output tile x 8 output channels per thread.
    int zero = MODEL_ZERO_INT;
#if CIN_SLICES == 1
    uint r0 = gt.y * 2, c0 = gt.x * 2;
#endif
    uint patch[4][4];
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
        uint rz = r0 + uint(zero) * q;
        [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++)
            patch[j][i] = tile[(rz + j) * LW + c0 + i][q];
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
            uint base = WINO_BASE + (h * 16 + c) * 32;
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
        float d[4][4], t[4][4], v[4][4];
        if ((c & 3) == 0) {
            uint rz = r0 + uint(zero) * (c >> 2);
            [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++)
                patch[j][i] = tile[(rz + j) * LW + c0 + i][c >> 2] ^ 0x80808080u;
        }
        [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++)
            d[j][i] = float((patch[j][i] >> (8 * (c & 3))) & 0xffu);
        [unroll] for (uint i = 0; i < 4; i++) {
            t[0][i] = d[0][i] - d[2][i]; t[1][i] = d[1][i] + d[2][i];
            t[2][i] = d[2][i] - d[1][i]; t[3][i] = d[1][i] - d[3][i];
        }
        [unroll] for (uint j = 0; j < 4; j++) {
            v[j][0] = t[j][0] - t[j][2]; v[j][1] = t[j][1] + t[j][2];
            v[j][2] = t[j][2] - t[j][1]; v[j][3] = t[j][1] - t[j][3];
        }
        v[1][1] -= 512.0;
#if CIN_SLICES > 1
        uint base = WINO_BASE + ((slice * CIN_SLICES + is) * 2 + h) * 512 + c * 32; // U[raw chunk][half][cin][p][k]
#else
        uint base = WINO_BASE + (h * 16 + c) * 32;
#endif
        [unroll] for (uint p = 0; p < 16; p++) {
#if WHALF
            uint4 wh = asuint(model[WINO16_BASE + (base - WINO_BASE) / 2 + p]); // FP16 pairs, exact (|U| <= 1152)
            float4 w0 = float4(f16tof32(wh.x), f16tof32(wh.x >> 16), f16tof32(wh.y), f16tof32(wh.y >> 16));
            float4 w1 = float4(f16tof32(wh.z), f16tof32(wh.z >> 16), f16tof32(wh.w), f16tof32(wh.w >> 16));
#else
            float4 w0 = model[base + p * 2], w1 = model[base + p * 2 + 1];
#endif
            float a = v[p >> 2][p & 3];
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
    int y[4][8];
#if PK16
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) y[px][k] = pk16_shr(acc[px][k], 2);
#else
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) y[px][k] = acc[px][k] >> 2;
#endif
#elif CIN_SLICES > 1
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
    int y[4][8];
#if PK16
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) y[px][k] = pk16_shr(acc[px][k], 2);
#else
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) y[px][k] = acc[px][k] >> 2;
#endif
#else
    const uint slice = 0;
    int y[4][8]; // [pixel: (0,0) (1,0) (0,1) (1,1)][k]
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
#endif
    uint2 words[4];
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint o = 0; o < 2; o++) {
#if CIN_SLICES > 1
        float4 s = scale[slice * 4 + h * 2 + o], b = bias[slice * 4 + h * 2 + o];
#else
        float4 s = scale[h * 2 + o], b = bias[h * 2 + o];
#endif
        int4 r4 = int4(float4(y[px][o * 4], y[px][o * 4 + 1], y[px][o * 4 + 2], y[px][o * 4 + 3]) * s + b);
        words[px][o] = pack_u8(min(max(r4, 0), 127));
    }
    // ---- exchange: half 0 stores the top pixel row, half 1 the bottom row.
    uint slot = (gt.y * GX + gt.x) * 2;
    if (h == 0) { swap[slot] = uint4(words[2], words[3]); }
    else        { swap[slot + 1] = uint4(words[0], words[1]); }
    GroupMemoryBarrierWithGroupSync();
    int ox = x0 + int(c0), oy = y0 + int(r0);
    if (h == 0) {
        uint4 o = swap[slot + 1];
        FG_STORE(dst,uint3(ox, oy, slice),1,uint4(words[0], o.xy));
        FG_STORE(dst,uint3(ox + 1, oy, slice),1,uint4(words[1], o.zw));
    } else {
        uint4 o = swap[slot];
        FG_STORE(dst,uint3(ox, oy + 1, slice),1,uint4(o.xy, words[2]));
        FG_STORE(dst,uint3(ox + 1, oy + 1, slice),1,uint4(o.zw, words[3]));
    }
}
