// SPDX-License-Identifier: MIT
// F4Q check (FreeFG 1.1, diagnostic only: BC250_XEFG_F4Q_SHADOW=1, src/game/f4q.h): this project's own passes that
// compare the output of the F4Q kernels with the output of the F(2x2) kernels on the GPU, on the game's real content.
// Fingerprint kernels (KIND 0..3, SRV 0|1) read one bound view and add a keyed 64-bit fingerprint of its bits into one
// slot of the slot ring (u1). Nothing of the content leaves the GPU: the CPU reads only the equal / not-equal counters
// the compare mode (KIND 4) adds into u2.
//   KIND 0  Texture2DArray<uint4>   (UINT formats)              read through the format, 4 components per texel
//   KIND 1  Texture2DArray<float4>  (UNORM/SNORM/FLOAT formats)  asuint of the decoded value
//   KIND 2  Texture2DArray<int4>    (SINT formats)
//   KIND 3  ByteAddressBuffer       raw 32-bit words of a buffer view's byte range
//   SRV 0: RW view at u0 (the profile's kernels); SRV 1: read-only view at t0 (not used by the add-on).
// Fingerprint of a view: lane0 = sum_i P(w_i ^ P(i ^ K0)), lane1 = sum_i P(P(w_i ^ K1) + P(~i)) (mod 2^32 each), over
// every 32-bit word w_i at element index i (texel index * 4 + component, or word index), P = the PCG RXS-M-XS
// permutation (a bijection, so a single changed word always changes both lanes), plus the element count. Order-free
// (wave sums and atomics), so any dispatch order gives the same slot.
// Slot: 16 bytes {lane0, lane1, count, tag}; the clear mode writes {0, 0, 0, tag} before a batch.
//
// KIND 4, aux modes (c0.x):
//   0 clear    slots [c0.y, c0.y + c0.z) = {0, 0, 0, c0.w}
//   1 compare  batch A (base c0.y) against batch B (base c0.z), c0.w slots; tags c1.x / c1.y (first and last slot of
//              each batch must carry them, else counters[1] += 1 and nothing else); input batches Ia = c1.z, Ib = c1.w,
//              c2.x slots, tags c2.y / c2.z; point c2.w; same-tick flag c3.x; forced input class c3.y (0xffffffff:
//              from the inputs: 0 differ, 1 equal; 2 when there are no inputs). Class = input class * 2 + same tick.
//              Per slot k: counters[KEY(point, k, class, ne)] += 1; per batch: counters[PT(point, class, any ne)] += 1;
//              counters[2] += 1.
//   2 stamp    counters[0] = counters[WORDS - 1] = c0.y (the CPU reads a readback copy only when both agree)
#ifndef KIND
#define KIND 0
#endif
#ifndef SRV
#define SRV 0
#endif
#define PE_PTBASE 16u
#define PE_KEYBASE 256u
#define PE_WORDS 8464u

cbuffer PeConstants : register(b0) {
    uint4 c0;
    uint4 c1;
    uint4 c2;
    uint4 c3;
};
RWByteAddressBuffer slots : register(u1);
RWByteAddressBuffer counters : register(u2);

#if KIND == 0
#if SRV
Texture2DArray<uint4> target : register(t0);
#else
RWTexture2DArray<uint4> target : register(u0);
#endif
#elif KIND == 1
#if SRV
Texture2DArray<float4> target : register(t0);
#else
RWTexture2DArray<float4> target : register(u0);
#endif
#elif KIND == 2
#if SRV
Texture2DArray<int4> target : register(t0);
#else
RWTexture2DArray<int4> target : register(u0);
#endif
#elif KIND == 3
#if SRV
ByteAddressBuffer target : register(t0);
#else
RWByteAddressBuffer target : register(u0);
#endif
#endif

uint pcg(uint v) {
    uint s = v * 747796405u + 2891336453u;
    uint w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u;
    return (w >> 22u) ^ w;
}

void acc(uint w, uint i, inout uint a0, inout uint a1) {
    a0 += pcg(w ^ pcg(i ^ 0x243f6a88u));
    a1 += pcg(pcg(w ^ 0x85a308d3u) + pcg(~i));
}

void flush(uint slot, uint a0, uint a1, uint n) {
    uint s0 = WaveActiveSum(a0);
    uint s1 = WaveActiveSum(a1);
    uint sn = WaveActiveSum(n);
    if (WaveIsFirstLane()) {
        slots.InterlockedAdd(slot * 16u + 0u, s0);
        slots.InterlockedAdd(slot * 16u + 4u, s1);
        slots.InterlockedAdd(slot * 16u + 8u, sn);
    }
}

#if KIND <= 2
uint4 load_bits(uint3 p) {
#if SRV
    return asuint(target.Load(int4(int3(p), 0)));
#else
    return asuint(target[p]);
#endif
}

// c0: x width, y height, z slices, w slot. Group (gx, gy, z) covers a 32 x 32 tile of slice z; thread t reads column
// t & 31 of rows (t >> 5) + 2i, i = 0..15 (coalesced rows).
[numthreads(64, 1, 1)]
void CSMain(uint3 gid : SV_GroupID, uint t : SV_GroupIndex) {
    uint a0 = 0u, a1 = 0u, n = 0u;
    uint x = gid.x * 32u + (t & 31u);
    uint z = gid.z;
    [loop] for (uint i = 0u; i < 16u; i++) {
        uint y = gid.y * 32u + (t >> 5u) + 2u * i;
        if (x < c0.x && y < c0.y && z < c0.z) {
            uint4 v = load_bits(uint3(x, y, z));
            uint e = ((z * c0.y + y) * c0.x + x) * 4u;
            acc(v.x, e, a0, a1);
            acc(v.y, e + 1u, a0, a1);
            acc(v.z, e + 2u, a0, a1);
            acc(v.w, e + 3u, a0, a1);
            n += 4u;
        }
    }
    flush(c0.w, a0, a1, n);
}
#elif KIND == 3
// c0: x words, y first word of the range inside the view, z groups per row of the dispatch, w slot. Group g =
// gid.y * c0.z + gid.x covers words [1024 g, 1024 g + 1024) of the range.
[numthreads(64, 1, 1)]
void CSMain(uint3 gid : SV_GroupID, uint t : SV_GroupIndex) {
    uint a0 = 0u, a1 = 0u, n = 0u;
    uint g = gid.y * c0.z + gid.x;
    [loop] for (uint i = 0u; i < 16u; i++) {
        uint k = g * 1024u + i * 64u + t;
        if (k < c0.x) {
            acc(target.Load((c0.y + k) * 4u), k, a0, a1);
            n += 1u;
        }
    }
    flush(c0.w, a0, a1, n);
}
#else
uint pt(uint pnt, uint cls, uint ne) { return PE_PTBASE + (pnt * 8u + cls) * 2u + ne; }
uint key(uint pnt, uint k, uint cls, uint ne) { return PE_KEYBASE + ((pnt * 64u + k) * 8u + cls) * 2u + ne; }
uint tag_of(uint slot) { return slots.Load(slot * 16u + 12u); }
bool batch_ok(uint base, uint n, uint tag) { return n == 0u || (tag_of(base) == tag && tag_of(base + n - 1u) == tag); }
bool slot_eq(uint a, uint b) { return all(slots.Load3(a * 16u) == slots.Load3(b * 16u)); }

[numthreads(1, 1, 1)]
void CSMain(uint3 gid : SV_GroupID) {
    uint mode = c0.x;
    if (mode == 0u) {
        [loop] for (uint i = 0u; i < c0.z; i++) slots.Store4((c0.y + i) * 16u, uint4(0u, 0u, 0u, c0.w));
        return;
    }
    if (mode == 2u) {
        counters.Store(0u, c0.y);
        counters.Store((PE_WORDS - 1u) * 4u, c0.y);
        return;
    }
    uint n = min(c0.w, 64u), ni = min(c2.x, 64u);
    if (!batch_ok(c0.y, n, c1.x) || !batch_ok(c0.z, n, c1.y) || !batch_ok(c1.z, ni, c2.y) || !batch_ok(c1.w, ni, c2.z)) {
        counters.InterlockedAdd(4u, 1u);
        return;
    }
    uint inputs = 2u;
    if (c3.y != 0xffffffffu) {
        inputs = c3.y;
    } else if (ni > 0u) {
        inputs = 1u;
        [loop] for (uint j = 0u; j < ni; j++) if (!slot_eq(c1.z + j, c1.w + j)) inputs = 0u;
    }
    uint cls = inputs * 2u + (c3.x ? 1u : 0u);
    uint pnt = c2.w;
    uint anyne = 0u;
    [loop] for (uint k = 0u; k < n; k++) {
        uint ne = slot_eq(c0.y + k, c0.z + k) ? 0u : 1u;
        anyne |= ne;
        counters.InterlockedAdd(key(pnt, k, cls, ne) * 4u, 1u);
    }
    counters.InterlockedAdd(pt(pnt, cls, anyne) * 4u, 1u);
    counters.InterlockedAdd(8u, 1u);
}
#endif
