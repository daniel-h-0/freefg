// SPDX-License-Identifier: MIT
// Exact fused Winograd F(2x2,3x3) 64->64 int8 3x3 convolution with clamp and dual-slope requantization (flow refinement).
Texture2DArray<uint4> activations : register(t0);
StructuredBuffer<float4> model : register(t1);
StructuredBuffer<int4> biases : register(t2);
StructuredBuffer<int4> slopes : register(t3);
RWTexture2DArray<uint4> outputImage : register(u0);
cbuffer Parameters : register(b0) { uint4 c0; uint4 c1; uint4 c2; }

#ifndef REF_BASE
#define REF_BASE 53249 // float4 index of U[chunk][half][cin][p][k8]: 36864-byte model, after the enc16 segment
#endif
#ifndef CLAMP_BITS
#define CLAMP_BITS 17
#endif
#ifndef CIN_SLICES
#define CIN_SLICES 4   // input slices of 16 channels: 4 = 64->64, 2 = 32->64
#endif
#ifndef ROLES
#define ROLES 8        // 8 output channels per role-wave; 8 roles = all 64 channels, 4 roles = two slices
#endif
#ifndef GX
#define GX 8           // tiles per group in x (GX * GY == 32: one role = one wave32)
#endif
#define GY (32 / GX)
#define CPT (16 / ROLES) // input channels transformed per thread per slice

// Inverse transform of the FP32 transform-domain sums m (exact integers) into int32 acc (= 4 x conv).
#define INVERSE_ACC \
        [unroll] for (uint k = 0; k < 8; k++) { \
            int mi[16]; \
            [unroll] for (uint p = 0; p < 16; p++) mi[p] = int(m[p][k]); \
            int rr[2][4]; \
            [unroll] for (uint i = 0; i < 4; i++) { \
                rr[0][i] = mi[i] + mi[4 + i] + mi[8 + i]; \
                rr[1][i] = mi[4 + i] - mi[8 + i] - mi[12 + i]; \
            } \
            acc[0][k] += rr[0][0] + rr[0][1] + rr[0][2]; acc[1][k] += rr[0][1] - rr[0][2] - rr[0][3]; \
            acc[2][k] += rr[1][0] + rr[1][1] + rr[1][2]; acc[3][k] += rr[1][1] - rr[1][2] - rr[1][3]; \
        }

#ifndef FLOAT_ALL
#define FLOAT_ALL 0
#endif
#ifndef STATIC_WORD
#define STATIC_WORD 0
#endif
#ifndef SERIAL_T
#define SERIAL_T 0
#endif
#ifndef VHALF
#define VHALF 0
#endif
#ifndef WHALF
#define WHALF 0
#endif
#ifndef REF16_BASE
#define REF16_BASE 69634 // float4 index of the FP16 U segment [chunk][half][cin][p] (8 halves): after the FP32 segment + zero
#endif
#if VHALF
// Transformed inputs are integers |v| <= 512: exact in FP16. Half the LDS of the float4 tile.
groupshared uint2 Vh[16 * 4 * 32];
#endif
groupshared float4 V[VHALF ? ROLES * 32 : 16 * 4 * 32]; // [cin][transform row][tile], one float4 = the row's four positions (epilogue exchange only when VHALF)

int quantize(int value, int negativeScale) {
    value = clamp(value, -(1 << CLAMP_BITS), (1 << CLAMP_BITS) - 1);
    uint ps = c2.z & 31, ns = (c2.z >> 8) & 31;
    int p = asint(asuint(max(value, 0)) * c2.y + (1u << ((ps + 31) & 31)));
    int n = asint(asuint(min(value, 0)) * asuint(negativeScale) + (1u << ((ns + 31) & 31)));
    return clamp((p >> ps) + (n >> ns), -128, 127);
}
uint pack4(int4 v) { return (asuint(v.x) & 255) | ((asuint(v.y) & 255) << 8) | ((asuint(v.z) & 255) << 16) | ((asuint(v.w) & 255) << 24); }

// xs/ys are texel coordinates, -1 outside the logical load bounds (a Load there returns 0 = int8 zeros).
uint load_word(int xs, int ys, uint is, uint q) {
    uint4 w = activations.Load(int4(xs, ys, int(is), 0));
    uint r = q == 0 ? w.x : q == 1 ? w.y : q == 2 ? w.z : w.w;
    return r ^ 0x80808080u;
}

[numthreads(32, ROLES, 1)]
void CSMain(uint3 gt : SV_GroupThreadID, uint3 gid : SV_GroupID) {
    uint t = gt.x;
    uint r = WaveReadLaneFirst(gt.y);
    uint kg = gid.z * ROLES + r, slice = kg >> 1, h = kg & 1;
    int X0 = int(gid.x * (2 * GX) + (t % GX) * 2), Y0 = int(gid.y * (2 * GY) + (t / GX) * 2);
    int xs[4], ys[4];
    [unroll] for (uint i = 0; i < 4; i++) {
        xs[i] = uint(X0 - 1 + int(i)) < c0.z ? X0 - 1 + int(i) : -1;
        ys[i] = uint(Y0 - 1 + int(i)) < c0.w ? Y0 + int(i) : -1;
    }
#if FLOAT_ALL
    // Owner-proven per model: 512 * max_{p,k} sum_{64 cin} |U| < 2^24, so the whole 64-channel sum is exact in FP32.
    float m[16][8];
    [unroll] for (uint p = 0; p < 16; p++) [unroll] for (uint k = 0; k < 8; k++) m[p][k] = 0;
#else
    int acc[4][8];
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) acc[px][k] = 0;
#endif
    [loop] for (uint is = 0; is < CIN_SLICES; is++) {
        // Transform: this thread's CPT channels (one 32-bit word) of its tile's 4x4 input patch.
        uint c_first = r * CPT, q = c_first >> 2;
#ifndef TIMING_NO_TRANSFORM
        uint wd[4][4];
#if STATIC_WORD
        // q is wave-uniform: one single-component load per texel instead of a uint4 plus selects.
#define LOAD_WORDS(C) [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++) \
            wd[j][i] = activations.Load(int4(xs[i], ys[j], int(is), 0)).C ^ 0x80808080u;
        [branch] switch (q) {
        case 0: LOAD_WORDS(x) break;
        case 1: LOAD_WORDS(y) break;
        case 2: LOAD_WORDS(z) break;
        default: LOAD_WORDS(w) break;
        }
#else
        [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++)
            wd[j][i] = load_word(xs[i], ys[j], is, q);
#endif
#if SERIAL_T
        [loop] for (uint cc = 0; cc < CPT; cc++) {
#else
        [unroll] for (uint cc = 0; cc < CPT; cc++) {
#endif
            uint b = (c_first & 3) + cc;
            float d[4][4], tt[4][4], v[4][4];
            [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint i = 0; i < 4; i++) d[j][i] = float((wd[j][i] >> (8 * b)) & 0xffu);
            [unroll] for (uint i = 0; i < 4; i++) {
                tt[0][i] = d[0][i] - d[2][i]; tt[1][i] = d[1][i] + d[2][i];
                tt[2][i] = d[2][i] - d[1][i]; tt[3][i] = d[1][i] - d[3][i];
            }
            [unroll] for (uint j = 0; j < 4; j++) {
                v[j][0] = tt[j][0] - tt[j][2]; v[j][1] = tt[j][1] + tt[j][2];
                v[j][2] = tt[j][2] - tt[j][1]; v[j][3] = tt[j][1] - tt[j][3];
            }
            v[1][1] -= 512.0;
            uint c = c_first + cc;
#if VHALF
            [unroll] for (uint j = 0; j < 4; j++) Vh[(c * 4 + j) * 32 + t] = uint2(f32tof16(v[j][0]) | (f32tof16(v[j][1]) << 16), f32tof16(v[j][2]) | (f32tof16(v[j][3]) << 16));
#else
            [unroll] for (uint j = 0; j < 4; j++) V[(c * 4 + j) * 32 + t] = float4(v[j][0], v[j][1], v[j][2], v[j][3]);
#endif
        }
#endif
        GroupMemoryBarrierWithGroupSync();
#if !FLOAT_ALL
        float m[16][8];
        [unroll] for (uint p = 0; p < 16; p++) [unroll] for (uint k = 0; k < 8; k++) m[p][k] = 0;
#endif
#ifdef TIMING_SAME_WEIGHTS
        uint base = REF_BASE + is * 1024; // timing only: every role streams the same coefficients
#else
        uint base = REF_BASE + ((slice * CIN_SLICES + is) * 2 + h) * 512;
#endif
#if WHALF
        uint base16 = REF16_BASE + ((slice * CIN_SLICES + is) * 2 + h) * 256;
#endif
#ifdef TIMING_LDS_ONCE
        float4 vfix[4];
#endif
        [unroll] for (uint c = 0; c < 16; c++) {
            float4 vr[4];
#ifdef TIMING_NO_LDS
            // timing only: per-lane values the compiler cannot fold (opaque zero from the model buffer)
            [unroll] for (uint j = 0; j < 4; j++) vr[j] = asfloat(uint4(t * 4 + j, c * 4 + j, is + j, t ^ j) + asuint(model[REF_BASE + 16 * 1024].x) + 0x3f800000u);
#elif defined(TIMING_LDS_ONCE)
            // timing only: one LDS read set per chunk, reused for all 16 channels
            if (c == 0) [unroll] for (uint j = 0; j < 4; j++) vfix[j] = V[j * 32 + t];
            [unroll] for (uint j = 0; j < 4; j++) vr[j] = vfix[j] * float(c + 1);
#elif VHALF
            [unroll] for (uint j = 0; j < 4; j++) { uint2 hv = Vh[(c * 4 + j) * 32 + t]; vr[j] = float4(f16tof32(hv.x), f16tof32(hv.x >> 16), f16tof32(hv.y), f16tof32(hv.y >> 16)); }
#else
            [unroll] for (uint j = 0; j < 4; j++) vr[j] = V[(c * 4 + j) * 32 + t];
#endif
            [unroll] for (uint p = 0; p < 16; p++) {
#ifdef TIMING_CONST_W
                float4 w0 = float4(p, p + 1, p + 2, p + 3) * (0.5 + c), w1 = float4(p + 4, p + 5, p + 6, p + 7) * (0.25 + c); // timing only
#elif WHALF
                // U is an integer |U| <= 1152: exact in FP16. 8 output channels per float4 as FP16 pairs, read
                // into SGPRs and consumed through v_fma_mix (half the scalar coefficient traffic).
                uint4 wh = asuint(model[base16 + c * 16 + p]);
                float4 w0 = float4(f16tof32(wh.x), f16tof32(wh.x >> 16), f16tof32(wh.y), f16tof32(wh.y >> 16));
                float4 w1 = float4(f16tof32(wh.z), f16tof32(wh.z >> 16), f16tof32(wh.w), f16tof32(wh.w >> 16));
#else
                float4 w0 = model[base + c * 32 + p * 2], w1 = model[base + c * 32 + p * 2 + 1];
#endif
                float a = vr[p >> 2][p & 3];
                m[p][0] = mad(a, w0.x, m[p][0]); m[p][1] = mad(a, w0.y, m[p][1]);
                m[p][2] = mad(a, w0.z, m[p][2]); m[p][3] = mad(a, w0.w, m[p][3]);
                m[p][4] = mad(a, w1.x, m[p][4]); m[p][5] = mad(a, w1.y, m[p][5]);
                m[p][6] = mad(a, w1.z, m[p][6]); m[p][7] = mad(a, w1.w, m[p][7]);
            }
        }
#if !FLOAT_ALL
        INVERSE_ACC
#endif
        GroupMemoryBarrierWithGroupSync();
    }
#if FLOAT_ALL
    int acc[4][8];
    [unroll] for (uint px = 0; px < 4; px++) [unroll] for (uint k = 0; k < 8; k++) acc[px][k] = 0;
    INVERSE_ACC
#endif
    // Epilogue: acc = 4 x conv (exact). Pixel order (0,0) (1,0) (0,1) (1,1).
    int4 bias0 = biases[slice * 4 + h * 2], bias1 = biases[slice * 4 + h * 2 + 1];
    int4 s0 = slopes[slice * 4 + h * 2], s1 = slopes[slice * 4 + h * 2 + 1];
    uint2 pw[4];
    [unroll] for (uint px = 0; px < 4; px++) {
        int4 lo = int4(acc[px][0], acc[px][1], acc[px][2], acc[px][3]) / 4 + bias0;
        int4 hi = int4(acc[px][4], acc[px][5], acc[px][6], acc[px][7]) / 4 + bias1;
        int4 ql, qh;
        [unroll] for (uint l = 0; l < 4; l++) { ql[l] = quantize(lo[l], s0[l]); qh[l] = quantize(hi[l], s1[l]); }
        pw[px] = uint2(pack4(ql), pack4(qh));
    }
    // Halves of a slice exchange words: half 0 stores the tile's top row, half 1 the bottom row.
    uint slot = r * 32 + t;
    if (h == 0) V[slot] = asfloat(uint4(pw[2], pw[3])); else V[slot] = asfloat(uint4(pw[0], pw[1]));
    GroupMemoryBarrierWithGroupSync();
    uint4 o = asuint(V[(r ^ 1) * 32 + t]);
    int oy = Y0 + int(h);
    uint4 left = h == 0 ? uint4(pw[0], o.xy) : uint4(o.xy, pw[2]);
    uint4 right = h == 0 ? uint4(pw[1], o.zw) : uint4(o.zw, pw[3]);
    if (oy < int(c1.y)) {
        if (X0 < int(c1.x)) outputImage[uint3(X0, oy + 1, slice)] = left;
        if (X0 + 1 < int(c1.x)) outputImage[uint3(X0 + 1, oy + 1, slice)] = right;
    }
}
