// SPDX-License-Identifier: MIT
// Exact Winograd F(2x2,3x3) int8 3x3 convolution + 2x2 max-pool of one input slice, the transform rows split across the two waves of a tile pair.
Texture2DArray<uint4> src : register(t0);
StructuredBuffer<float4> model : register(t1);
StructuredBuffer<float4> scale : register(t2);
StructuredBuffer<float4> bias : register(t3);
RWTexture2DArray<uint4> dst : register(u0);

#ifndef WHALF
#define WHALF 0 // coefficients as FP16 pairs from a segment at WINO16_BASE (float4 index)
#endif
#ifndef WINO_BASE
#define WINO_BASE 720
#endif
#ifndef DECODE_OFFSET
#define DECODE_OFFSET 1
#endif
#ifndef SLICES
#define SLICES 1
#endif
#ifndef GX
#define GX 8
#endif
#ifndef GY
#define GY 4
#endif
#ifndef NOPOOL
#define NOPOOL 0
#endif
#ifndef CLAMP_LO
#define CLAMP_LO 0
#endif
#ifndef XU1
#define XU1 0 // 1: FP16-pair input transform and wave-uniform epilogue (needs -enable-16bit-types); same results
#endif
#define WINO_ZERO (WINO_BASE + 1024 * SLICES)
#if DECODE_OFFSET
uint decode_word(uint w) { return (w + 0x80808080u) ^ 0x80808080u; }
#else
uint decode_word(uint w) { return w ^ 0x80808080u; }
#endif
#if XU1
// The codes d = decode_word(w) bytes (0..255, signed value d - 128) as FP16 1024 + d, two channels per register:
// channels (0, 1) for sel 0, (2, 3) for sel 1. The decode's final XOR is folded into the exponent bits: for an
// unpacked byte b, (b ^ 0x6480) is the FP16 bit pattern of 1024 + (b ^ 0x80); key 0x647f gives 1024 + (255 - d), the
// complemented code. FP16 holds every integer of magnitude <= 2048 exactly. unpack_u8u16 keeps the four values one
// vector through dxil-spirv, so the transform becomes packed FP16 arithmetic.
#if DECODE_OFFSET
uint decode_raw(uint w) { return w + 0x80808080u; }
#else
uint decode_raw(uint w) { return w; }
#endif
float16_t2 code_pair(uint raw, uint sel, uint16_t key) {
    float16_t4 L4 = asfloat16(unpack_u8u16((uint8_t4_packed)raw) ^ key);
    return sel ? L4.zw : L4.xy;
}
#endif

// Row-partial exchange: [row pair][tile][4 pixels x 8 channels of the partner's half] as int4.
groupshared int4 part[2 * GX * GY * 8];
#if NOPOOL
groupshared uint4 swap4[GX * GY * 2];
#else
groupshared uint2 upper[GX * GY];
#endif

[numthreads(GX, GY, 2)]
void CSMain(uint3 id : SV_DispatchThreadID, uint3 gt : SV_GroupThreadID, uint3 gid : SV_GroupID) {
#if SLICES > 1
    uint slice = gid.z;
#else
    const uint slice = 0;
#endif
    uint rp = WaveReadLaneFirst(gt.z); // transform rows {2rp, 2rp+1}
    int x0 = int(id.x) * 2 - 1, y0 = int(id.y) * 2 - 1;
    // One instruction stream for both waves: local rows L = (d0, d1, d2) for rp 0, (d2, d3, d1) for rp 1, and
    //   t_a = L0 - L2,  t_b = s * L1 + L2  (s = +1 / -1)
    // gives Bt rows (0, 1) = (d0 - d2, d1 + d2) or (2, 3) = (d2 - d1, d1 - d3). Exact: small integers.
    int rowoff[3] = { rp ? 2 : 0, rp ? 3 : 1, rp ? 1 : 2 };
#if XU1
    // XU1: the same transform values in FP16 pairs, L = 1024 + code (exact), signed values s = code - 128:
    //   rp 0: L = (d0, 255 - d1, d2):  t_a = L0 - L2 = s0 - s2,  t_b = L2 - L1 = s1 + s2 + 1
    //   rp 1: L = (d2, d3, d1):        t_a = L0 - L2 = s2 - s1,  t_b = L2 - L1 = s1 - s3
    // Row 1 of rp 0 is decoded complemented (the decode's XOR key). The +1 of rp 0's t_b cancels in the column
    // transform except at v[1][1] (+2), which loses it there: v = B^T s B exactly, the release kernel's values.
    // Every operand and result is an integer of magnitude <= 2048 (|t| <= 255, |v| <= 512), so each FP16 operation
    // is exact. `precise` keeps the compiler from regrouping sums of two biased values (L + L' is not exact in FP16).
    uint16_t key1 = rp ? uint16_t(0x6480) : uint16_t(0x647f);
    float16_t corr = rp ? float16_t(0.0) : float16_t(2.0);
    int zero = asint(model[WINO_ZERO].x);
    float m[8][16]; // [local position (row-in-pair * 4 + col)][output channel]
    [unroll] for (uint p = 0; p < 8; p++) [unroll] for (uint k = 0; k < 16; k++) m[p][k] = 0;
    [unroll] for (uint q = 0; q < 4; q++) {
        int xz = x0 + zero * int(q);
        uint pw[3][4];
        [unroll] for (uint j = 0; j < 3; j++) [unroll] for (uint i = 0; i < 4; i++)
            pw[j][i] = decode_raw(src.Load(int4(xz + int(i), y0 + rowoff[j], 0, 0))[q]);
        float16_t2 vh[2][8]; // [sel][local position]: sel 0 = channels (4q, 4q + 1), sel 1 = (4q + 2, 4q + 3)
        [unroll] for (uint sel = 0; sel < 2; sel++) {
            precise float16_t2 t[2][4];
            precise float16_t2 v[2][4];
            [unroll] for (uint i = 0; i < 4; i++) {
                float16_t2 L0 = code_pair(pw[0][i], sel, uint16_t(0x6480)), L1 = code_pair(pw[1][i], sel, key1);
                float16_t2 L2 = code_pair(pw[2][i], sel, uint16_t(0x6480));
                t[0][i] = L0 - L2; t[1][i] = L2 - L1;
            }
            [unroll] for (uint j = 0; j < 2; j++) {
                v[j][0] = t[j][0] - t[j][2]; v[j][1] = t[j][1] + t[j][2];
                v[j][2] = t[j][2] - t[j][1]; v[j][3] = t[j][1] - t[j][3];
            }
            v[1][1] -= float16_t2(corr, corr);
            [unroll] for (uint p = 0; p < 8; p++) vh[sel][p] = v[p >> 2][p & 3];
        }
        [unroll] for (uint cc = 0; cc < 4; cc++) {
            uint c = q * 4 + cc;
            [unroll] for (uint hh = 0; hh < 2; hh++) {
                uint base = WINO_BASE + slice * 1024 + (hh * 16 + c) * 32 + rp * 16; // U[slice][half][cin][p][k8], p = 8rp + local
                [unroll] for (uint p = 0; p < 8; p++) {
#if WHALF
                    uint4 wh = asuint(model[WINO16_BASE + (base - WINO_BASE) / 2 + p]); // FP16 pairs, exact (|U| <= 1152)
                    float4 w0 = float4(f16tof32(wh.x), f16tof32(wh.x >> 16), f16tof32(wh.y), f16tof32(wh.y >> 16));
                    float4 w1 = float4(f16tof32(wh.z), f16tof32(wh.z >> 16), f16tof32(wh.w), f16tof32(wh.w >> 16));
#else
                    float4 w0 = model[base + p * 2], w1 = model[base + p * 2 + 1];
#endif
                    float a = float((cc & 1) ? vh[cc >> 1][p].y : vh[cc >> 1][p].x);
                    m[p][hh * 8 + 0] = mad(a, w0.x, m[p][hh * 8 + 0]); m[p][hh * 8 + 1] = mad(a, w0.y, m[p][hh * 8 + 1]);
                    m[p][hh * 8 + 2] = mad(a, w0.z, m[p][hh * 8 + 2]); m[p][hh * 8 + 3] = mad(a, w0.w, m[p][hh * 8 + 3]);
                    m[p][hh * 8 + 4] = mad(a, w1.x, m[p][hh * 8 + 4]); m[p][hh * 8 + 5] = mad(a, w1.y, m[p][hh * 8 + 5]);
                    m[p][hh * 8 + 6] = mad(a, w1.z, m[p][hh * 8 + 6]); m[p][hh * 8 + 7] = mad(a, w1.w, m[p][hh * 8 + 7]);
                }
            }
        }
    }
    // Column inverse per local row; this wave's contribution to the two output rows (wave-uniform branches, no
    // per-lane selects): rows {0,1}: P(0,c) = Z0 + Z1, P(1,c) = Z1; rows {2,3}: P(0,c) = Z2, P(1,c) = -Z2 - Z3.
    // Wave rp keeps output-channel half rp and sends the other half's partials to its partner.
    uint tile = gt.y * GX + gt.x, other = rp ^ 1;
    int mine[4][8];
    [branch] if (rp == 0) {
        int send[4][8];
        [unroll] for (uint k = 0; k < 16; k++) {
            int z0a = int(m[0][k]) + int(m[1][k]) + int(m[2][k]), z0b = int(m[1][k]) - int(m[2][k]) - int(m[3][k]);
            int z1a = int(m[4][k]) + int(m[5][k]) + int(m[6][k]), z1b = int(m[5][k]) - int(m[6][k]) - int(m[7][k]);
            int P4[4] = { z0a + z1a, z0b + z1b, z1a, z1b };
            [unroll] for (uint px = 0; px < 4; px++) { if (k < 8) mine[px][k] = P4[px]; else send[px][k - 8] = P4[px]; }
        }
        [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint o = 0; o < 2; o++)
            part[tile * 8 + px * 2 + o] = int4(send[px][o * 4], send[px][o * 4 + 1], send[px][o * 4 + 2], send[px][o * 4 + 3]);
    } else {
        int send[4][8];
        [unroll] for (uint k = 0; k < 16; k++) {
            int z0a = int(m[0][k]) + int(m[1][k]) + int(m[2][k]), z0b = int(m[1][k]) - int(m[2][k]) - int(m[3][k]);
            int z1a = int(m[4][k]) + int(m[5][k]) + int(m[6][k]), z1b = int(m[5][k]) - int(m[6][k]) - int(m[7][k]);
            int P4[4] = { z0a, z0b, -z0a - z1a, -z0b - z1b };
            [unroll] for (uint px = 0; px < 4; px++) { if (k < 8) send[px][k] = P4[px]; else mine[px][k - 8] = P4[px]; }
        }
        [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint o = 0; o < 2; o++)
            part[(GX * GY + tile) * 8 + px * 2 + o] = int4(send[px][o * 4], send[px][o * 4 + 1], send[px][o * 4 + 2], send[px][o * 4 + 3]);
    }
    GroupMemoryBarrierWithGroupSync();
#else
    float sgn = rp ? -1.0 : 1.0, corr = rp ? 0.0 : 512.0;
    int zero = asint(model[WINO_ZERO].x);
    uint patch[3][4];
    float m[8][16]; // [local position (row-in-pair * 4 + col)][output channel]
    [unroll] for (uint p = 0; p < 8; p++) [unroll] for (uint k = 0; k < 16; k++) m[p][k] = 0;
    [unroll] for (uint c = 0; c < 16; c++) {
        if ((c & 3) == 0) {
            int xz = x0 + zero * int(c >> 2);
            [unroll] for (uint j = 0; j < 3; j++) [unroll] for (uint i = 0; i < 4; i++)
                patch[j][i] = decode_word(src.Load(int4(xz + int(i), y0 + rowoff[j], 0, 0))[c >> 2]);
        }
        float d[3][4], t[2][4], v[2][4];
        [unroll] for (uint j = 0; j < 3; j++) [unroll] for (uint i = 0; i < 4; i++)
            d[j][i] = float((patch[j][i] >> (8 * (c & 3))) & 0xffu);
        // Bt rows: 0 = d0 - d2, 1 = d1 + d2, 2 = d2 - d1, 3 = d1 - d3. Local rows dl = d[rp .. rp+2].
        [unroll] for (uint i = 0; i < 4; i++) { t[0][i] = d[0][i] - d[2][i]; t[1][i] = mad(sgn, d[1][i], d[2][i]); }
        [unroll] for (uint j = 0; j < 2; j++) {
            v[j][0] = t[j][0] - t[j][2]; v[j][1] = t[j][1] + t[j][2];
            v[j][2] = t[j][2] - t[j][1]; v[j][3] = t[j][1] - t[j][3];
        }
        v[1][1] -= corr;
        [unroll] for (uint hh = 0; hh < 2; hh++) {
            uint base = WINO_BASE + slice * 1024 + (hh * 16 + c) * 32 + rp * 16; // U[slice][half][cin][p][k8], p = 8rp + local
            [unroll] for (uint p = 0; p < 8; p++) {
#if WHALF
                uint4 wh = asuint(model[WINO16_BASE + (base - WINO_BASE) / 2 + p]); // FP16 pairs, exact (|U| <= 1152)
                float4 w0 = float4(f16tof32(wh.x), f16tof32(wh.x >> 16), f16tof32(wh.y), f16tof32(wh.y >> 16));
                float4 w1 = float4(f16tof32(wh.z), f16tof32(wh.z >> 16), f16tof32(wh.w), f16tof32(wh.w >> 16));
#else
                float4 w0 = model[base + p * 2], w1 = model[base + p * 2 + 1];
#endif
                float a = v[p >> 2][p & 3];
                m[p][hh * 8 + 0] = mad(a, w0.x, m[p][hh * 8 + 0]); m[p][hh * 8 + 1] = mad(a, w0.y, m[p][hh * 8 + 1]);
                m[p][hh * 8 + 2] = mad(a, w0.z, m[p][hh * 8 + 2]); m[p][hh * 8 + 3] = mad(a, w0.w, m[p][hh * 8 + 3]);
                m[p][hh * 8 + 4] = mad(a, w1.x, m[p][hh * 8 + 4]); m[p][hh * 8 + 5] = mad(a, w1.y, m[p][hh * 8 + 5]);
                m[p][hh * 8 + 6] = mad(a, w1.z, m[p][hh * 8 + 6]); m[p][hh * 8 + 7] = mad(a, w1.w, m[p][hh * 8 + 7]);
            }
        }
    }
    // Column inverse per local row, then this pair's contribution to the two output rows:
    //   rows {0,1}: P(0,c) = Z0 + Z1, P(1,c) = Z1;  rows {2,3}: P(0,c) = Z2, P(1,c) = -Z2 - Z3.
    int P[4][16]; // pixel (0,0) (1,0) (0,1) (1,1)
    [unroll] for (uint k = 0; k < 16; k++) {
        int z[2][2];
        [unroll] for (uint j = 0; j < 2; j++) {
            int a0 = int(m[j * 4][k]), a1 = int(m[j * 4 + 1][k]), a2 = int(m[j * 4 + 2][k]), a3 = int(m[j * 4 + 3][k]);
            z[j][0] = a0 + a1 + a2; z[j][1] = a1 - a2 - a3;
        }
        [unroll] for (uint cx = 0; cx < 2; cx++) {
            P[cx][k] = z[0][cx] + (rp ? 0 : z[1][cx]);
            P[2 + cx][k] = rp ? -z[0][cx] - z[1][cx] : z[1][cx];
        }
    }
    // Wave rp finishes output-channel half rp: send the other half's partials, receive the partner's.
    uint tile = gt.y * GX + gt.x, other = rp ^ 1;
    int mine[4][8], send[4][8];
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) {
        mine[px][k] = rp ? P[px][8 + k] : P[px][k];
        send[px][k] = rp ? P[px][k] : P[px][8 + k];
    }
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint o = 0; o < 2; o++)
        part[((rp * GX * GY) + tile) * 8 + px * 2 + o] = int4(send[px][o * 4], send[px][o * 4 + 1], send[px][o * 4 + 2], send[px][o * 4 + 3]);
    GroupMemoryBarrierWithGroupSync();
#endif
    int yv[4][8];
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint o = 0; o < 2; o++) {
        int4 q = part[((other * GX * GY) + tile) * 8 + px * 2 + o];
        yv[px][o * 4 + 0] = mine[px][o * 4 + 0] + q.x; yv[px][o * 4 + 1] = mine[px][o * 4 + 1] + q.y;
        yv[px][o * 4 + 2] = mine[px][o * 4 + 2] + q.z; yv[px][o * 4 + 3] = mine[px][o * 4 + 3] + q.w;
    }
    uint h = rp; // from here on, identical to wino_enc16's epilogue for channel half h
#if NOPOOL
    uint2 pw[4];
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint o = 0; o < 2; o++) {
        float4 s = scale[slice * 4 + h * 2 + o], b = bias[slice * 4 + h * 2 + o];
        int4 r4 = int4(float4(yv[px][o * 4] >> 2, yv[px][o * 4 + 1] >> 2, yv[px][o * 4 + 2] >> 2, yv[px][o * 4 + 3] >> 2) * s + b);
        pw[px][o] = pack_u8(min(max(r4, CLAMP_LO), 127));
    }
    uint slot = tile * 2;
    if (h == 0) swap4[slot] = uint4(pw[2], pw[3]); else swap4[slot + 1] = uint4(pw[0], pw[1]);
    GroupMemoryBarrierWithGroupSync();
    uint ox = id.x * 2, oy = id.y * 2;
    if (h == 0) { uint4 o = swap4[slot + 1]; dst[uint3(ox, oy, slice)] = uint4(pw[0], o.xy); dst[uint3(ox + 1, oy, slice)] = uint4(pw[1], o.zw); }
    else        { uint4 o = swap4[slot];     dst[uint3(ox, oy + 1, slice)] = uint4(o.xy, pw[2]); dst[uint3(ox + 1, oy + 1, slice)] = uint4(o.zw, pw[3]); }
#else
    int q8[8];
    [unroll] for (uint k = 0; k < 8; k++) q8[k] = max(max(yv[0][k], yv[1][k]), max(yv[2][k], yv[3][k])) >> 2;
    uint2 words;
    [unroll] for (uint o = 0; o < 2; o++) {
        float4 s = scale[slice * 4 + h * 2 + o], b = bias[slice * 4 + h * 2 + o];
        int4 r4 = int4(float4(q8[o * 4], q8[o * 4 + 1], q8[o * 4 + 2], q8[o * 4 + 3]) * s + b);
        r4 = min(max(r4, 0), 127);
        words[o] = pack_u8(r4);
    }
    if (h == 1) upper[tile] = words;
    GroupMemoryBarrierWithGroupSync();
    if (h == 0) dst[uint3(id.xy, slice)] = uint4(words, upper[tile]);
#endif
}
