// SPDX-License-Identifier: MIT
// Exact Winograd F(2x2,3x3) int8 3x3 convolution of a skip input plus a 2x-upsampled low-resolution input (decoder stage), scale/bias, clamp and pack.
Texture2DArray<uint4> low : register(t0);
StructuredBuffer<float4> model : register(t1);
StructuredBuffer<float4> scale : register(t2);
StructuredBuffer<float4> bias : register(t3);
Texture2DArray<uint4> skip : register(t4);
RWTexture2DArray<uint4> dst : register(u0);
cbuffer Dims : register(b0) { int W; int H; };

#ifndef WHALF
#define WHALF 0 // coefficients as FP16 pairs from a segment at WINO16_BASE (float4 index)
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
        int fz = asint(model[WINO_ZERO].x);
        int Xm = 2 * lx - 1, Xp = 2 * lx, Ym = 2 * ly - 1, Yp = 2 * ly;
        bool xm = Xm < 0 || Xm > W - 1, xp = Xp < 0 || Xp > W - 1, ym = Ym < 0 || Ym > H - 1, yp = Yp < 0 || Yp > H - 1;
        [unroll] for (uint q = 0; q < 4; q++) {
            int zq = fz * int(q);
            int4 a = unpack_s8s32(low.Load(int4(lx - 1 + zq, ly - 1, SLICE_ARG, 0))[q]), b = unpack_s8s32(low.Load(int4(lx + zq, ly - 1, SLICE_ARG, 0))[q]);
            int4 c = unpack_s8s32(low.Load(int4(lx - 1 + zq, ly, SLICE_ARG, 0))[q]), d = unpack_s8s32(low.Load(int4(lx + zq, ly, SLICE_ARG, 0))[q]);
            uint wtl = fill_word(unpack_s8s32(skip.Load(int4(Xm + zq, Ym, SLICE_ARG, 0))[q]), up(a, b, c, d));
            uint wtr = fill_word(unpack_s8s32(skip.Load(int4(Xp + zq, Ym, SLICE_ARG, 0))[q]), up(b, d, a, c));
            uint wbl = fill_word(unpack_s8s32(skip.Load(int4(Xm + zq, Yp, SLICE_ARG, 0))[q]), up(c, a, d, b));
            uint wbr = fill_word(unpack_s8s32(skip.Load(int4(Xp + zq, Yp, SLICE_ARG, 0))[q]), up(d, c, b, a));
            tile[(2 * j) * LW + 2 * i][q] = (xm || ym) ? 0 : wtl;
            tile[(2 * j) * LW + 2 * i + 1][q] = (xp || ym) ? 0 : wtr;
            tile[(2 * j + 1) * LW + 2 * i][q] = (xm || yp) ? 0 : wbl;
            tile[(2 * j + 1) * LW + 2 * i + 1][q] = (xp || yp) ? 0 : wbr;
        }
#else
        uint4 L00 = low.Load(int4(lx - 1, ly - 1, SLICE_ARG, 0)), L10 = low.Load(int4(lx, ly - 1, SLICE_ARG, 0));
        uint4 L01 = low.Load(int4(lx - 1, ly, SLICE_ARG, 0)), L11 = low.Load(int4(lx, ly, SLICE_ARG, 0));
        int Xm = 2 * lx - 1, Xp = 2 * lx, Ym = 2 * ly - 1, Yp = 2 * ly;
        uint4 Smm = skip.Load(int4(Xm, Ym, SLICE_ARG, 0)), Spm = skip.Load(int4(Xp, Ym, SLICE_ARG, 0));
        uint4 Smp = skip.Load(int4(Xm, Yp, SLICE_ARG, 0)), Spp = skip.Load(int4(Xp, Yp, SLICE_ARG, 0));
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
    int zero = asint(model[WINO_ZERO].x);
#if CIN_SLICES == 1
    uint r0 = gt.y * 2, c0 = gt.x * 2;
#endif
    uint patch[4][4];
#if !(CIN_SLICES > 1 && FLOAT_ALL)
    float m[16][8];
    [unroll] for (uint p = 0; p < 16; p++) [unroll] for (uint k = 0; k < 8; k++) m[p][k] = 0;
#endif
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
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) y[px][k] = acc[px][k] >> 2;
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
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) y[px][k] = acc[px][k] >> 2;
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
        y[0][k] = (r[0][0] + r[0][1] + r[0][2]) >> 2; y[1][k] = (r[0][1] - r[0][2] - r[0][3]) >> 2;
        y[2][k] = (r[1][0] + r[1][1] + r[1][2]) >> 2; y[3][k] = (r[1][1] - r[1][2] - r[1][3]) >> 2;
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
        dst[uint3(ox, oy, slice)] = uint4(words[0], o.xy);
        dst[uint3(ox + 1, oy, slice)] = uint4(words[1], o.zw);
    } else {
        uint4 o = swap[slot];
        dst[uint3(ox, oy + 1, slice)] = uint4(o.xy, words[2]);
        dst[uint3(ox + 1, oy + 1, slice)] = uint4(o.zw, words[3]);
    }
}
