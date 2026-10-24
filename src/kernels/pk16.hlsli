// SPDX-License-Identifier: MIT
// pk16.hlsli: the packed-FP16 form (PK16=1, with XU1=1 and WHALF=1) of the F(2x2,3x3) U-Net kernels wino_enc16.hlsl,
// wino_dec16.hlsl and wino_row16.hlsl (FreeFG 1.1.2's default; release/profile-mfg <hash>.fp16.dxil).
//   - The model owner adds a copy of the layer's exact transform-domain coefficients U' (integers, |U'| <= 1152) scaled by
//     2^-8, in FP16 (exact): src/model_f4q.h, the FP16 forms' segment.
//   - The input transform v is exact in FP16 (integers |v| <= 512; XU1).
//   - Per 16-channel input slice, one FP16 chain in ascending input-channel order over output-channel pairs: packed FMAs
//     (v_pk_fma_f16), each rounded once to FP16 (round to nearest even). With the 2^-8 prescale every operand and partial
//     sum is a multiple of 2^-8, so no value is subnormal, and no partial sum can overflow (16 * 512 * 1152 * 2^-8 = 36864;
//     48 * 256 * 384 * 2^-8 = 18432 in wino_row16; plus at most 256 / 384 of rounding growth, below FP16's 65504).
//   - Each slice's chains are flushed into FP32 as value * 2^8 (integers below 2^24: exact) and added exactly.
//   - The exact kernels' integer inverse transform and pooling follow, then the division by 4 (by 2 in wino_row16) rounded
//     to nearest even (the exact kernels' floor shift is exact only for exact sums).
// The FP16 chain rounds, so the outputs can differ from the exact F(2x2) kernels' outputs. mad() on half2 is not
// `precise`, so the driver may fuse it: the BC-250 runs v_pk_fma_f16 (one rounding per step); a CPU rasteriser may round
// the product and the sum separately. The flushes and the epilogue are integer-exact.
// No coefficient, weight or model value appears here: the kernels read them at run time.
#if !WHALF
#error "PK16 reads the FP16 coefficient pairs (WHALF=1)"
#endif
#if !XU1
#error "PK16's packed MACs need the FP16-pair input transform (XU1=1)"
#endif

// x / 2^n rounded to nearest even (n = 1 or 2).
int pk16_shr(int x, uint n) {
    int fl = x >> n;
    uint rem = uint(x - (fl << n)), half = 1u << (n - 1u);
    return fl + ((rem > half || (rem == half && (fl & 1) != 0)) ? 1 : 0);
}
