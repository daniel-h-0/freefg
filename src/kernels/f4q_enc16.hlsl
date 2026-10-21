// SPDX-License-Identifier: MIT
// F4Q encoder (FreeFG 1.1): FP32 Winograd F(4x4,3x3) form of the U-Net encoder layer of f030948d (wino_rs16.hlsl, the
// F(2x2) form; interface in f4q_common.hlsli): 16 int8 input channels -> 16 output channels per slice (SLICES slices,
// SV_GroupID.z), 2x2 max-pool, requantised.
// Structure: six waves per group over the same 8 x 4 tiles (32 x 16 px); wave i owns row i of the 6 x 6 transform
// domain for all 16 output channels (96 accumulators). The staging holds the decoded input codes as FP16 pairs (exact);
// each wave computes its own transform row from it (column pass for one Bt row, then the row pass), then the channel
// chain (mad() in channel order), the output transform over the horizontal index first, the vertical one in ZROUNDS
// rounds through LDS, pooling, round(y * fl(1/576)), requantisation by "finalize units" (word, v pair), a [word][px][tile]
// output exchange and row-contiguous texel stores.
// Exactness: as f4q_dec16.hlsl (matched the F(2x2) kernel in every test; no proof for every input).
// Defines: POOL (1), DECODE_OFFSET (1), ZROUNDS (2 | 4), TBASE (the segment's float4 index in the model buffer, checked
//          by the model owner), SLICES (1: output slices of 16 channels, SV_GroupID.z; the table holds them one after
//          the other, scale and bias as [slice * 4 + word], dst layer = slice).
#include "f4q_common.hlsli"

#ifndef ZROUNDS
#define ZROUNDS 2
#endif
#ifndef TBASE
#define TBASE 9
#endif
#ifndef SLICES
#define SLICES 1
#endif
#define TGX 8
#define TGY 4
#define SX (4 * TGX + 2)
#define SY (4 * TGY + 2)
#define PITCH SX                  // skewed: word = row * 34 + col + (row >> 2)
#define OFS(i) (i)
#define PLANE ((SY - 1) * PITCH + SX + ((SY - 1) >> 2))
#define SINW (8 * PLANE)
#define CPR (16 / ZROUNDS)            // output channels per Z round
#define ZW (6 * 4 * CPR * 32)         // Z floats per round: [row i][v][channel in round][tile]
#define UNIONW (SINW > ZW ? SINW : ZW)
#if POOL
#define NPX 4
#else
#define NPX 16
#endif
#define PADW 40                       // out exchange: [word][px][tile] with 40-word rows: conflict-free both ways
#define OUTW (4 * NPX * PADW)
// out exchange after the staging-only tail of the union when it fits there (staging is dead after the main loop)
#define OUTBASE 0
#define LTOT (UNIONW > OUTW ? UNIONW : OUTW)
groupshared uint L[LTOT];
uint pk16(float lo, float hi) { return f32tof16(lo) | (f32tof16(hi) << 16); }

void bt6(float a, float b, float c, float d, float e, float f, out float o[6]) {
    float ec = e - c, db = d - b;
    o[0] = mad(4.0, a - c, ec);
    o[1] = mad(-4.0, b + c, d + e);
    o[2] = mad(4.0, b - c, e - d);
    o[3] = mad(2.0, db, ec);
    o[4] = mad(-2.0, db, ec);
    o[5] = mad(-4.0, db, f - d);
}
void at6(float a, float b, float c, float d, float e, float f, out float o[4]) {
    float s1 = b + c, s2 = d + e, d1 = b - c, d2 = d - e;
    o[0] = a + s1 + s2;
    o[1] = d1 + 2 * d2;
    o[2] = s1 + 4 * s2;
    o[3] = d1 + 8 * d2 + f;
}

[numthreads(32, 6, 1)]
void CSMain(uint3 gt : SV_GroupThreadID, uint3 gid : SV_GroupID) {
    uint t = gt.x, i = WaveReadLaneFirst(gt.y);
#if SLICES > 1
    uint slice = gid.z;
#else
    const uint slice = 0;
#endif
    uint tx = t % TGX, ty = t / TGX;
    int gx0 = int(gid.x * (4 * TGX)) - 1, gy0 = int(gid.y * (4 * TGY)) - 1;
    {
        uint lin = gt.y * 32 + gt.x;
        [unroll] for (uint it = 0; it < (SX * SY + 191) / 192; it++) {
            uint idx = lin + it * 192;
            if (idx < SX * SY) {
                uint sy = idx / SX, sx = idx - sy * SX;
                uint4 w = src.Load(int4(gx0 + int(sx), gy0 + int(sy), 0, 0));
                uint a = sy * PITCH + sx + (sy >> 2);
                uint dw[4] = { decode_word(w.x), decode_word(w.y), decode_word(w.z), decode_word(w.w) };
                [unroll] for (uint q = 0; q < 4; q++) {
                    L[(2 * q) * PLANE + a] = pk16(float(dw[q] & 0xffu), float((dw[q] >> 8) & 0xffu));
                    L[(2 * q + 1) * PLANE + a] = pk16(float((dw[q] >> 16) & 0xffu), float(dw[q] >> 24));
                }
            }
        }
    }
    GroupMemoryBarrierWithGroupSync();

    // Bt row i on a column (rows d0..d5): o = alpha * (d[P] + s1 * d[Q]) + (d[R] + s2 * d[S]), exact small integers.
    //   i: P Q s1 | R S s2 | alpha  =  0: 0 2 - | 4 2 - | 4;  1: 1 2 + | 3 4 + | -4;  2: 1 2 - | 4 3 - | 4;
    //                                  3: 3 1 - | 4 2 - | 2;  4: 3 1 - | 4 2 - | -2;  5: 1 3 - | 5 3 - | 4
    uint rP = (0x133110u >> (4 * i)) & 15u, rQ = (0x311222u >> (4 * i)) & 15u;
    uint rR = (0x544434u >> (4 * i)) & 15u, rS = (0x322342u >> (4 * i)) & 15u;
    float s12 = (i == 1) ? 1.0 : -1.0;
    float alpha = (i == 1) ? -4.0 : (i == 3) ? 2.0 : (i == 4) ? -2.0 : 4.0;
    float corr = (i == 1) ? 4608.0 : 0.0; // offset decode: Bt 1 = (0, -6, 0, 0, 0, 0), 128 * 36 at (1, 1)
    uint sbase = 4 * ty * PITCH + 4 * tx + ty;
    uint aP = sbase + rP * PITCH + (rP >> 2), aQ = sbase + rQ * PITCH + (rQ >> 2);
    uint aR = sbase + rR * PITCH + (rR >> 2), aS = sbase + rS * PITCH + (rS >> 2);
    uint rb = WaveReadLaneFirst(TBASE + (slice * 6 + i) * (16 * 6 * 4));   // float4: [c][j][4] = U' [i][j][c][4q .. 4q+3]

    float m[6][16];
    [unroll] for (uint j0 = 0; j0 < 6; j0++) [unroll] for (uint k0 = 0; k0 < 16; k0++) m[j0][k0] = 0;
    [unroll] for (uint pp = 0; pp < 8; pp++) {
        float o2[6][2];
        [unroll] for (uint col = 0; col < 6; col++) {
            uint wP = L[pp * PLANE + aP + OFS(col)], wQ = L[pp * PLANE + aQ + OFS(col)];
            uint wR = L[pp * PLANE + aR + OFS(col)], wS = L[pp * PLANE + aS + OFS(col)];
            [unroll] for (uint hs = 0; hs < 2; hs++) {
                uint sh = 16 * hs;
                float x = mad(s12, f16tof32(wQ >> sh), f16tof32(wP >> sh));
                float y = mad(s12, f16tof32(wS >> sh), f16tof32(wR >> sh));
                o2[col][hs] = mad(alpha, x, y);
            }
        }
        [unroll] for (uint hh = 0; hh < 2; hh++) {
            uint c = 2 * pp + hh;
            float v[6];
            bt6(o2[0][hh], o2[1][hh], o2[2][hh], o2[3][hh], o2[4][hh], o2[5][hh], v);
            v[1] -= corr;
            [unroll] for (uint j = 0; j < 6; j++) {
                [unroll] for (uint q = 0; q < 4; q++) {
                    float4 w = model[rb + (c * 6 + j) * 4 + q];
                    m[j][4 * q + 0] = mad(v[j], w.x, m[j][4 * q + 0]); m[j][4 * q + 1] = mad(v[j], w.y, m[j][4 * q + 1]);
                    m[j][4 * q + 2] = mad(v[j], w.z, m[j][4 * q + 2]); m[j][4 * q + 3] = mad(v[j], w.w, m[j][4 * q + 3]);
                }
            }
        }
    }
    const float inv = 1.0 / 576.0;
    // rows first: Z[v][k] = (M[i][.] A)[v]
    float z[4][16];
    [unroll] for (uint k1 = 0; k1 < 16; k1++) {
        float o4[4];
        at6(m[0][k1], m[1][k1], m[2][k1], m[3][k1], m[4][k1], m[5][k1], o4);
        [unroll] for (uint v1 = 0; v1 < 4; v1++) z[v1][k1] = o4[v1];
    }
    // finalize units per round: (word in round, v pair); CPR / 4 words x 2 pairs
#define UNITS (CPR / 2)
#if POOL
#define WPU 2
#else
#define WPU 8
#endif
    uint wo[ZROUNDS][WPU];
    uint zw = i * 4 * CPR * 32 + t;
    [unroll] for (uint h = 0; h < ZROUNDS; h++) {
        GroupMemoryBarrierWithGroupSync(); // staging (h = 0) or the previous round's Z fully read
        [unroll] for (uint v2 = 0; v2 < 4; v2++) [unroll] for (uint kk = 0; kk < CPR; kk++)
            L[zw + (v2 * CPR + kk) * 32] = asuint(z[v2][h * CPR + kk]);
        GroupMemoryBarrierWithGroupSync();
        if (i < UNITS) {
            uint wr = i >> 1, vp = i & 1;          // word in round, v pair
            uint zb = (2 * vp * CPR + 4 * wr) * 32 + t;
            uint wdo = h * (CPR / 4) + wr;         // output word 0..3
            float y[4][2][4];                      // [u][v in pair][channel]
            [unroll] for (uint vv = 0; vv < 2; vv++) [unroll] for (uint ch = 0; ch < 4; ch++) {
                float zz[6];
                [unroll] for (uint ii = 0; ii < 6; ii++)
                    zz[ii] = asfloat(L[zb + ((ii * 4 + vv) * CPR + ch) * 32]);
                float o4[4];
                at6(zz[0], zz[1], zz[2], zz[3], zz[4], zz[5], o4);
                [unroll] for (uint u = 0; u < 4; u++) y[u][vv][ch] = o4[u];
            }
            float4 s = scale[slice * 4 + wdo], b = bias[slice * 4 + wdo];
#if POOL
            [unroll] for (uint uh = 0; uh < 2; uh++) {
                float4 q;
                [unroll] for (uint ch = 0; ch < 4; ch++)
                    q[ch] = round(max(max(y[2 * uh][0][ch], y[2 * uh][1][ch]), max(y[2 * uh + 1][0][ch], y[2 * uh + 1][1][ch])) * inv);
                wo[h][uh] = requant4(q, s, b);
            }
#else
            [unroll] for (uint u = 0; u < 4; u++) [unroll] for (uint vv = 0; vv < 2; vv++) {
                float4 q = float4(round(y[u][vv][0] * inv), round(y[u][vv][1] * inv), round(y[u][vv][2] * inv), round(y[u][vv][3] * inv));
                wo[h][u * 2 + vv] = requant4(q, s, b);
            }
#endif
        }
    }
    GroupMemoryBarrierWithGroupSync(); // last round's Z reads done: the out area overlays Z
    if (i < UNITS) {
        uint wr = i >> 1, vp = i & 1;
        [unroll] for (uint h = 0; h < ZROUNDS; h++) {
            uint wdo = h * (CPR / 4) + wr;
#if POOL
            [unroll] for (uint uh = 0; uh < 2; uh++) L[OUTBASE + (wdo * NPX + uh * 2 + vp) * PADW + t] = wo[h][uh];
#else
            [unroll] for (uint u = 0; u < 4; u++) [unroll] for (uint vv = 0; vv < 2; vv++)
                L[OUTBASE + (wdo * NPX + u * 4 + 2 * vp + vv) * PADW + t] = wo[h][u * 2 + vv];
#endif
        }
    }
    GroupMemoryBarrierWithGroupSync();
#if POOL
    // 16 x 8 output texels, rows 2i, 2i + 1 for waves 0..3: one row-contiguous store per wave
    if (i < 4) {
        uint n = i * 32 + t, x = n % 16, y = n / 16;
        uint tile = (y >> 1) * TGX + (x >> 1), px = (y & 1) * 2 + (x & 1);
        uint4 o = uint4(L[OUTBASE + (0 * NPX + px) * PADW + tile], L[OUTBASE + (1 * NPX + px) * PADW + tile],
                        L[OUTBASE + (2 * NPX + px) * PADW + tile], L[OUTBASE + (3 * NPX + px) * PADW + tile]);
        dst[uint3(gid.x * 16 + x, gid.y * 8 + y, slice)] = o;
    }
#else
    // 32 x 16 output texels: waves 0..3 store rows 4i .. 4i + 3, 32 contiguous texels each
    if (i < 4) {
        [unroll] for (uint e = 0; e < 4; e++) {
            uint y = 4 * i + e, x = t;
            uint tile = (y >> 2) * TGX + (x >> 2), px = (y & 3) * 4 + (x & 3);
            uint4 o = uint4(L[OUTBASE + (0 * NPX + px) * PADW + tile], L[OUTBASE + (1 * NPX + px) * PADW + tile],
                            L[OUTBASE + (2 * NPX + px) * PADW + tile], L[OUTBASE + (3 * NPX + px) * PADW + tile]);
            dst[uint3(gid.x * 32 + x, gid.y * 16 + y, slice)] = o;
        }
    }
#endif
}
