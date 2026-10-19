// SPDX-License-Identifier: MIT
// Exact 1D Winograd F(2,3) int8 3x3 convolution (16->16 or 32->16, signed output), two horizontal pixels x 16 output channels per thread.
Texture2DArray<uint4> src : register(t0);
StructuredBuffer<float4> model : register(t1);
StructuredBuffer<float4> scale : register(t2);
StructuredBuffer<float4> bias : register(t3);
RWTexture2DArray<uint4> dst : register(u0);

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

[numthreads(4, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID) {
    int x0 = int(id.x) * 2 - 1, y0 = int(id.y) - 1;
    float m[4][16];
    [unroll] for (uint j = 0; j < 4; j++) [unroll] for (uint k = 0; k < 16; k++) m[j][k] = 0;
    [unroll] for (uint is = 0; is < CIN_SLICES; is++) {
        [unroll] for (uint q = 0; q < 4; q++) {
            uint wd[3][4];
            [unroll] for (uint r = 0; r < 3; r++) [unroll] for (uint i = 0; i < 4; i++)
                wd[r][i] = src.Load(int4(x0 + int(i), y0 + int(r), int(is), 0))[q] ^ 0x80808080u;
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
        }
    }
    uint4 o0, o1;
    [unroll] for (uint o = 0; o < 4; o++) {
        float4 s = scale[o], b = bias[o];
        int4 ya, yb;
        [unroll] for (uint l = 0; l < 4; l++) {
            uint k = o * 4 + l;
            int a0 = int(m[0][k]), a1 = int(m[1][k]), a2 = int(m[2][k]), a3 = int(m[3][k]);
            ya[l] = (a0 + a1 + a2) >> 1; yb[l] = (a1 - a2 - a3) >> 1;
        }
        o0[o] = pack_u8(min(max(int4(float4(ya) * s + b), CLAMP_LO), 127));
        o1[o] = pack_u8(min(max(int4(float4(yb) * s + b), CLAMP_LO), 127));
    }
    dst[uint3(id.x * 2, id.y, 0)] = o0;
    dst[uint3(id.x * 2 + 1, id.y, 0)] = o1;
}
