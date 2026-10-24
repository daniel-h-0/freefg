// SPDX-License-Identifier: MIT
// F4Q decoder (FreeFG 1.1): FP32 Winograd F(4x4,3x3) form of the U-Net decoder layer of b3941ac8 (wino_dec16.hlsl, the
// F(2x2) form): 3x3 convolution, 16 -> 16 int8 channels, over clamp(skip + up2(low), 0, 127) per channel (skip W x H,
// low W/2 x H/2, 16 int8 channels each; up2 = the same truncating 9-3-3-1 bilinear weights and the same zero texels
// outside the images as wino_dec16.hlsl), "same" zero padding, then q = int(float(y) * scale + bias) clamped to
// [0, 127] and packed. Resources and the Dims constants are wino_dec16.hlsl's, so both kernels bind the same way.
// Own code: every coefficient is read at run time from `model`, the segment the add-on's model owner writes from the
// network's own weights (src/model_f4q.h: U' = G' g G'^T, G' = 24 G, FP32); no weight, scale or bias value appears here.
//
// Structure: six waves per group over the same 8 x 4 tiles (32 x 16 px); wave i owns row i of the 6 x 6 transform
// domain for all 16 output channels. The fill writes each staged texel's 16 channels as FP16 pairs (values 0..127,
// exact) into a 34 x 18 window on a skewed 34-word pitch; each wave computes its own transform row from it, then the
// channel chain (mad() in channel order), the output transform over the horizontal index first, the vertical one in
// ZROUNDS rounds through LDS, round(y * fl(1/576)), requantisation, and row-contiguous stores.
// Exactness: the F(2x2) kernels' outputs are exact; this form rounds in its FP32 sums. Its outputs matched them in
// every test (FreeFG 1.1: 20 SDK test rows and in-game comparisons on the BC-250), which does not prove every input.
// Defines: ZROUNDS (4 | 2), TBASE (the segment's float4 index in the model buffer, checked by the model owner),
// UP_SHIFT (1), and three forms (FreeFG 1.1.2; release/profile-mfg/origin.json):
//   XU2D (0 | 1; 1 needs -enable-16bit-types): the fill in packed 16-bit integers and the column pass in packed FP16;
//          every FP16 and 16-bit integer operation is exact, so the outputs are the XU2D=0 form's for every input.
//   TRIM (0 | 1): a group whose 16 output rows all lie at or below the destination's height (dst.GetDimensions, not
//          Dims.H) returns at entry: its typed stores would all be out of bounds and discarded by the bounds check, and it
//          touches nothing else outside its own LDS. The condition is uniform over the group and precedes every load and
//          barrier, so the outputs are the TRIM=0 form's for every input.
//   HALF_TABLE (0 | 1): the coefficients as FP16 U'/2 pairs at TBASE (the model owner's FP16 table), scale 1/288. U'/2 rounds
//          to FP16 where it needs more than 11 significant bits, so the outputs can differ from the HALF_TABLE=0 form's.
// The F4Q decoder of 1.1.2 is XU2D=1 TRIM=1 (<hash>.f4q.dxil); its FP16 form adds HALF_TABLE=1 (<hash>.fp16.dxil).
Texture2DArray<uint4> low : register(t0);
StructuredBuffer<float4> model : register(t1);  // the F4Q coefficient segment from float4 TBASE (src/model_f4q.h)
StructuredBuffer<float4> scale : register(t2);  // [output channel / 4]
StructuredBuffer<float4> bias : register(t3);
Texture2DArray<uint4> skip : register(t4);
RWTexture2DArray<uint4> dst : register(u0);
cbuffer Dims : register(b0) { int W; int H; };

#ifndef ZROUNDS
#define ZROUNDS 4
#endif
#ifndef TBASE
#define TBASE 9
#endif
#ifndef UP_SHIFT
#define UP_SHIFT 1
#endif
#ifndef TRIM
#define TRIM 0
#endif
#ifndef XU2D
#define XU2D 0 // 1: packed 16-bit fill and column pass (the same results)
#endif
#ifndef HALF_TABLE
#define HALF_TABLE 0 // 1: FP16 U'/2 coefficient pairs, scale 1/288 (the outputs can differ)
#endif
#define TGX 8
#define TGY 4
#define SX (4 * TGX + 2)
#define SY (4 * TGY + 2)
#define PITCH SX                  // skewed: word = row * 34 + col + (row >> 2)
#define PLANE ((SY - 1) * PITCH + SX + ((SY - 1) >> 2))
#define SINW (8 * PLANE)
#define CPR (16 / ZROUNDS)            // output channels per Z round
#define ZW (6 * 4 * CPR * 32)         // Z floats per round: [row i][v][channel in round][tile]
#define UNIONW (SINW > ZW ? SINW : ZW)
#define NPX 16
#define PADW 40                       // out exchange: [word][px][tile] with 40-word rows
#define OUTW (4 * NPX * PADW)
#define LTOT (UNIONW > OUTW ? UNIONW : OUTW)
#if XU2D
// XU2D: the staged texels in a 16-bit typed array of their own (FP16 channel pairs, the same word layout as L's staging
// planes), so the column pass reads half2 values (packed FP16 arithmetic); L keeps the Z rounds and the out exchange.
// 4928 + 3072 words = 32,000 B: still two groups per CU.
#define LZO (ZW > OUTW ? ZW : OUTW)
groupshared half2 S2[SINW];
groupshared uint L[LZO];
#else
groupshared uint L[LTOT];
#endif
uint pk16(float lo, float hi) { return f32tof16(lo) | (f32tof16(hi) << 16); }

int4 up(int4 a, int4 b, int4 c, int4 d) {
#if UP_SHIFT
    int4 s = 9 * a + 3 * (b + c) + d;
    return (s + int4(uint4(s) >> 28)) >> 4; // truncating /16 (|s| <= 2048), as wino_dec16.hlsl UP_SHIFT=1
#else
    return (9 * a + 3 * (b + c) + d) / 16;
#endif
}
// One staged texel: 16 channels clamp(s + u, 0, 127) as four FP16-pair words (channel pairs 2p, 2p + 1 -> plane p),
// or zeros outside the image.
void stage_texel(uint a, uint4 S, uint4 A, uint4 B, uint4 Cc, uint4 D, bool outside) {
    [unroll] for (uint q = 0; q < 4; q++) {
        int4 v = clamp(unpack_s8s32(S[q]) + up(unpack_s8s32(A[q]), unpack_s8s32(B[q]), unpack_s8s32(Cc[q]), unpack_s8s32(D[q])), 0, 127);
        L[(2 * q) * PLANE + a] = outside ? 0u : pk16(float(v.x), float(v.y));
        L[(2 * q + 1) * PLANE + a] = outside ? 0u : pk16(float(v.z), float(v.w));
    }
}

#if XU2D
// XU2D fill, in packed 16-bit integers (two channels per register), the same values as stage_texel and up():
// unpack_s8s16 gives the signed codes of word q as channel pairs (4q, 4q + 1) and (4q + 2, 4q + 3) = planes 2q and
// 2q + 1; T = 9a + 3(b + c) + d (|T| <= 2048), trunc(T / 16) = (T + (uint16(T) >> 12)) >> 4 (T >= -2048: the top four
// bits are 1111 exactly when T < 0), then clamp(s + q, 0, hi) (hi = 127, or 0 for a texel outside the image) and the
// FP16 pair by OR 0x6400 (1024 + v, exact for 0 <= v <= 1023) and a packed FP16 subtract of 1024. Every intermediate
// fits 16 bits (u16 wrap-around in the sums is harmless: T, q and s + q are in [-2048, 2032] and [-256, 254]).
int16_t4 code_s16(uint w) { return unpack_s8s16((int8_t4_packed)w); }
half2 fill_pair(int16_t2 s, int16_t2 T, int16_t2 hi) {
    int16_t2 q = (T + int16_t2(uint16_t2(T) >> uint16_t(12))) >> int16_t(4);
    uint16_t2 v = uint16_t2(min(max(s + q, int16_t(0)), hi));
    return asfloat16(v | uint16_t(0x6400)) - half(1024.0);
}
#endif

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
#if TRIM
    // TRIM: the group's output rows are gid.y * 16 + 0 .. 15. Group row 0 always holds image row 0, so only gid.y > 0
    // reads the size: dst's descriptor read then does not dominate the stores and is not kept live through the kernel.
    [branch] if (gid.y > 0) {
        uint dw, dh, dl;
        dst.GetDimensions(dw, dh, dl);
        if (gid.y * (4 * TGY) >= dh) return;
    }
#endif
    uint t = gt.x, i = WaveReadLaneFirst(gt.y);
    uint tx = t % TGX, ty = t / TGX;
    {
        // ---- fill: low-resolution position (lx, ly) covers staging columns 2p, 2p + 1 and rows 2r, 2r + 1, i.e.
        // full-resolution X = 2 lx - 1, 2 lx and Y = 2 ly - 1, 2 ly (the window starts at 32 gx - 1, 16 gy - 1).
        uint lin = gt.y * 32 + gt.x;
        if (lin < (SX / 2) * (SY / 2)) {
#if XU2D
            // lin / 17 as (lin * 241) >> 12 (exact for lin < 192: the error lin / 69632 stays below 1 / 17), all in 24 bits
            uint ur = (lin * 241u) >> 12;
            int p = int(lin - ur * 17u), r = int(ur);
#else
            int p = int(lin % (SX / 2)), r = int(lin / (SX / 2));
#endif
            int lx = p + int(gid.x) * (2 * TGX), ly = r + int(gid.y) * (2 * TGY);
            uint4 L00 = low.Load(int4(lx - 1, ly - 1, 0, 0)), L10 = low.Load(int4(lx, ly - 1, 0, 0));
            uint4 L01 = low.Load(int4(lx - 1, ly, 0, 0)), L11 = low.Load(int4(lx, ly, 0, 0));
            int Xm = 2 * lx - 1, Xp = 2 * lx, Ym = 2 * ly - 1, Yp = 2 * ly;
            uint4 Smm = skip.Load(int4(Xm, Ym, 0, 0)), Spm = skip.Load(int4(Xp, Ym, 0, 0));
            uint4 Smp = skip.Load(int4(Xm, Yp, 0, 0)), Spp = skip.Load(int4(Xp, Yp, 0, 0));
            bool xm = Xm < 0 || Xm > W - 1, xp = Xp < 0 || Xp > W - 1, ym = Ym < 0 || Ym > H - 1, yp = Yp < 0 || Yp > H - 1;
            uint sx = uint(2 * p), sy = uint(2 * r);
#if XU2D
            // the same words (sy * PITCH = 68 r, (sy >> 2) = ((sy + 1) >> 2) = r >> 1) with 24-bit products
            uint a0 = ur * (2 * PITCH) + sx + (ur >> 1), a1 = a0 + PITCH;
            // stage_texel's four texels (a, b, c, d) = mm (L00, L10, L01, L11), pm (L10, L11, L00, L01),
            // mp (L01, L00, L11, L10), pp (L11, L01, L10, L00): mm and pp share b + c = L10 + L01, pm and mp L11 + L00.
            int16_t2 hmm = (xm || ym) ? int16_t2(0, 0) : int16_t2(127, 127), hpm = (xp || ym) ? int16_t2(0, 0) : int16_t2(127, 127);
            int16_t2 hmp = (xm || yp) ? int16_t2(0, 0) : int16_t2(127, 127), hpp = (xp || yp) ? int16_t2(0, 0) : int16_t2(127, 127);
            [unroll] for (uint q = 0; q < 4; q++) {
                int16_t4 u00 = code_s16(L00[q]), u10 = code_s16(L10[q]), u01 = code_s16(L01[q]), u11 = code_s16(L11[q]);
                int16_t4 umm = code_s16(Smm[q]), upm = code_s16(Spm[q]), ump = code_s16(Smp[q]), upp = code_s16(Spp[q]);
                [unroll] for (uint hs = 0; hs < 2; hs++) {
                    int16_t2 c00 = hs ? u00.zw : u00.xy, c10 = hs ? u10.zw : u10.xy, c01 = hs ? u01.zw : u01.xy, c11 = hs ? u11.zw : u11.xy;
                    int16_t2 bcA = c10 + c01, bcB = c11 + c00;
                    int16_t2 tmm = c00 * int16_t(9) + (bcA * int16_t(3) + c11), tpp = c11 * int16_t(9) + (bcA * int16_t(3) + c00);
                    int16_t2 tpm = c10 * int16_t(9) + (bcB * int16_t(3) + c01), tmp = c01 * int16_t(9) + (bcB * int16_t(3) + c10);
                    uint plane = (2 * q + hs) * PLANE;
                    S2[plane + a0] = fill_pair(hs ? umm.zw : umm.xy, tmm, hmm);
                    S2[plane + a0 + 1] = fill_pair(hs ? upm.zw : upm.xy, tpm, hpm);
                    S2[plane + a1] = fill_pair(hs ? ump.zw : ump.xy, tmp, hmp);
                    S2[plane + a1 + 1] = fill_pair(hs ? upp.zw : upp.xy, tpp, hpp);
                }
            }
#else
            uint a0 = sy * PITCH + sx + (sy >> 2), a1 = (sy + 1) * PITCH + sx + ((sy + 1) >> 2);
            stage_texel(a0, Smm, L00, L10, L01, L11, xm || ym);
            stage_texel(a0 + 1, Spm, L10, L11, L00, L01, xp || ym);
            stage_texel(a1, Smp, L01, L00, L11, L10, xm || yp);
            stage_texel(a1 + 1, Spp, L11, L01, L10, L00, xp || yp);
#endif
        }
    }
    GroupMemoryBarrierWithGroupSync();

    // Bt row i on a column (rows d0..d5): o = alpha * (d[P] + s1 * d[Q]) + (d[R] + s2 * d[S]), exact small integers.
    uint rP = (0x133110u >> (4 * i)) & 15u, rQ = (0x311222u >> (4 * i)) & 15u;
    uint rR = (0x544434u >> (4 * i)) & 15u, rS = (0x322342u >> (4 * i)) & 15u;
    float s12 = (i == 1) ? 1.0 : -1.0;
    float alpha = (i == 1) ? -4.0 : (i == 3) ? 2.0 : (i == 4) ? -2.0 : 4.0;
    uint sbase = 4 * ty * PITCH + 4 * tx + ty;
    uint aP = sbase + rP * PITCH + (rP >> 2), aQ = sbase + rQ * PITCH + (rQ >> 2);
    uint aR = sbase + rR * PITCH + (rR >> 2), aS = sbase + rS * PITCH + (rS >> 2);
#if HALF_TABLE
    uint rb = WaveReadLaneFirst(TBASE + i * (16 * 6 * 2));   // uint4: [c][j][2] = U'/2 [i][j][c][0 .. 15] FP16 pairs
#else
    uint rb = WaveReadLaneFirst(TBASE + i * (16 * 6 * 4));   // float4: [c][j][4] = U' [i][j][c][4q .. 4q+3]
#endif

    float m[6][16];
    [unroll] for (uint j0 = 0; j0 < 6; j0++) [unroll] for (uint k0 = 0; k0 < 16; k0++) m[j0][k0] = 0;
#if XU2D
    // XU2D: the column pass on FP16 channel pairs (packed FMA): every operand and result is an integer, |x|, |y| <= 254,
    // |o| <= 1016 (row 1: -4 (d1 + d2) + d3 + d4), so each operation is exact. The row pass's first level (eight sums
    // or differences of two column values, |.| <= 2032) is exact in FP16 too; its second level runs in FP32 with the
    // FP16 operands folded in (v_fma_mix). The values equal bt6's on the FP32 column values exactly.
    half2 s12h = half2(half(s12), half(s12)), alphah = half2(half(alpha), half(alpha));
    [unroll] for (uint pp = 0; pp < 8; pp++) {
        half2 o2[6];
        [unroll] for (uint col = 0; col < 6; col++) {
            half2 P = S2[pp * PLANE + aP + col], Q = S2[pp * PLANE + aQ + col];
            half2 R = S2[pp * PLANE + aR + col], Sv = S2[pp * PLANE + aS + col];
            o2[col] = mad(alphah, mad(s12h, Q, P), mad(s12h, Sv, R));
        }
        half2 ec = o2[4] - o2[2], db = o2[3] - o2[1], ac = o2[0] - o2[2], bc = o2[1] + o2[2];
        half2 de = o2[3] + o2[4], bmc = o2[1] - o2[2], emd = o2[4] - o2[3], fmd = o2[5] - o2[3];
        [unroll] for (uint hh = 0; hh < 2; hh++) {
            uint c = 2 * pp + hh;
            float v[6];
            v[0] = mad(4.0, float(ac[hh]), float(ec[hh]));
            v[1] = mad(-4.0, float(bc[hh]), float(de[hh]));
            v[2] = mad(4.0, float(bmc[hh]), float(emd[hh]));
            v[3] = mad(2.0, float(db[hh]), float(ec[hh]));
            v[4] = mad(-2.0, float(db[hh]), float(ec[hh]));
            v[5] = mad(-4.0, float(db[hh]), float(fmd[hh]));
            [unroll] for (uint j = 0; j < 6; j++) {
#if HALF_TABLE
                uint4 h0 = asuint(model[rb + (c * 6 + j) * 2]), h1 = asuint(model[rb + (c * 6 + j) * 2 + 1]);
                uint hw[8] = { h0.x, h0.y, h0.z, h0.w, h1.x, h1.y, h1.z, h1.w };
                [unroll] for (uint k = 0; k < 16; k++)
                    m[j][k] = mad(v[j], f16tof32((k & 1) ? (hw[k >> 1] >> 16) : hw[k >> 1]), m[j][k]);
#else
                [unroll] for (uint q = 0; q < 4; q++) {
                    float4 w = model[rb + (c * 6 + j) * 4 + q];
                    m[j][4 * q + 0] = mad(v[j], w.x, m[j][4 * q + 0]); m[j][4 * q + 1] = mad(v[j], w.y, m[j][4 * q + 1]);
                    m[j][4 * q + 2] = mad(v[j], w.z, m[j][4 * q + 2]); m[j][4 * q + 3] = mad(v[j], w.w, m[j][4 * q + 3]);
                }
#endif
            }
        }
    }
#else
    [unroll] for (uint pp = 0; pp < 8; pp++) {
        float o2[6][2];
        [unroll] for (uint col = 0; col < 6; col++) {
            uint wP = L[pp * PLANE + aP + col], wQ = L[pp * PLANE + aQ + col];
            uint wR = L[pp * PLANE + aR + col], wS = L[pp * PLANE + aS + col];
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
            [unroll] for (uint j = 0; j < 6; j++) {
#if HALF_TABLE
                uint4 h0 = asuint(model[rb + (c * 6 + j) * 2]), h1 = asuint(model[rb + (c * 6 + j) * 2 + 1]);
                uint hw[8] = { h0.x, h0.y, h0.z, h0.w, h1.x, h1.y, h1.z, h1.w };
                [unroll] for (uint k = 0; k < 16; k++)
                    m[j][k] = mad(v[j], f16tof32((k & 1) ? (hw[k >> 1] >> 16) : hw[k >> 1]), m[j][k]);
#else
                [unroll] for (uint q = 0; q < 4; q++) {
                    float4 w = model[rb + (c * 6 + j) * 4 + q];
                    m[j][4 * q + 0] = mad(v[j], w.x, m[j][4 * q + 0]); m[j][4 * q + 1] = mad(v[j], w.y, m[j][4 * q + 1]);
                    m[j][4 * q + 2] = mad(v[j], w.z, m[j][4 * q + 2]); m[j][4 * q + 3] = mad(v[j], w.w, m[j][4 * q + 3]);
                }
#endif
            }
        }
    }
#endif
#if HALF_TABLE
    const float inv = 1.0 / 288.0;
#else
    const float inv = 1.0 / 576.0;
#endif
    // x first: Z[v][k] = (M[i][.] A)[v] on the wave's own transform row
    float z[4][16];
    [unroll] for (uint k1 = 0; k1 < 16; k1++) {
        float o4[4];
        at6(m[0][k1], m[1][k1], m[2][k1], m[3][k1], m[4][k1], m[5][k1], o4);
        [unroll] for (uint v1 = 0; v1 < 4; v1++) z[v1][k1] = o4[v1];
    }
#define UNITS (CPR / 2)
    uint wo[ZROUNDS][8];
    uint zw = i * 4 * CPR * 32 + t;
    [unroll] for (uint h = 0; h < ZROUNDS; h++) {
#if XU2D
        if (h > 0) GroupMemoryBarrierWithGroupSync(); // the previous round's Z fully read (staging is S2, not L)
#else
        GroupMemoryBarrierWithGroupSync(); // staging (h = 0) or the previous round's Z fully read
#endif
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
            float4 s = scale[wdo], b = bias[wdo];
            [unroll] for (uint u = 0; u < 4; u++) [unroll] for (uint vv = 0; vv < 2; vv++) {
                float4 q = float4(round(y[u][vv][0] * inv), round(y[u][vv][1] * inv), round(y[u][vv][2] * inv), round(y[u][vv][3] * inv));
                int4 r = int4(q * s + b);
                wo[h][u * 2 + vv] = pack_u8(min(max(r, 0), 127));
            }
        }
    }
    GroupMemoryBarrierWithGroupSync(); // last round's Z reads done: the out area overlays Z
    if (i < UNITS) {
        uint wr = i >> 1, vp = i & 1;
        [unroll] for (uint h = 0; h < ZROUNDS; h++) {
            uint wdo = h * (CPR / 4) + wr;
            [unroll] for (uint u = 0; u < 4; u++) [unroll] for (uint vv = 0; vv < 2; vv++)
                L[(wdo * NPX + u * 4 + 2 * vp + vv) * PADW + t] = wo[h][u * 2 + vv];
        }
    }
    GroupMemoryBarrierWithGroupSync();
    // 32 x 16 output texels: waves 0..3 store rows 4i .. 4i + 3, 32 contiguous texels each
    if (i < 4) {
        [unroll] for (uint e = 0; e < 4; e++) {
            uint yy = 4 * i + e, x = t;
            uint tile = (yy >> 2) * TGX + (x >> 2), px = (yy & 3) * 4 + (x & 3);
            uint4 o = uint4(L[(0 * NPX + px) * PADW + tile], L[(1 * NPX + px) * PADW + tile],
                            L[(2 * NPX + px) * PADW + tile], L[(3 * NPX + px) * PADW + tile]);
            dst[uint3(gid.x * 32 + x, gid.y * 16 + yy, 0)] = o;
        }
    }
}
