# Shader profile: origin and rebuild

This directory holds the shader-profile files of FreeFG that the Intel-free builds load: 33 compute shaders (DXIL)
and 9 tables and markers, 42 files in all. Every shader is compiled from this project's HLSL in `src/kernels/`, and
`release/build_profile.py` compiles each one again and compares the bytes. None of these files contains model weights.
The kernels read the network's coefficients at run time, from the buffers that Intel's XeSS Frame Generation runtime
creates, after the add-on's model owner has re-laid them out.

FreeFG works with Intel XeSS Frame Generation. It is not affiliated with or endorsed by Intel. Intel and XeSS are
trademarks of Intel Corporation.

## Check it yourself

1. Download Microsoft's DirectX Shader Compiler release
   [v1.9.2607 for Linux](https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/linux_dxc_2026_07_29.x86_x64.tar.gz)
   (sha256 `55665c87824051ed4774ff3280a79ccbbb7d39243b9736ca5e98222134112d54`, 515,588,543 bytes) and extract it.
2. Run:

   ```sh
   XEMFG_DXC=/path/to/linux_dxc_2026_07_29.x86_x64 python3 release/build_profile.py check
   ```

   The expected result is `"result": "pass"` with `"rebuilt_byte_identical": 33`.

Another DXC version compiles the same sources to different bytes. For example, v1.9.2609 gives a different
`e83e868f8d5d2c0f.dxil`. `check` compares the DXC files with the pin in `release/inputs.lock.json` (toolchain
`profile`) and reports the version it ran. Without `XEMFG_DXC`, `check` runs every step except the rebuild and says so.

`check` also confirms that:
- the directory holds exactly the shader, table and marker files listed in `origin.json`;
- each file's sha256 matches `origin.json` and the lock's profile pins;
- each shader has its recorded shader model;
- `waves.txt` lists each shader's module hash;
- every file under `src/kernels/` starts with an SPDX line.

## How each shader is built

`origin.json` holds the recipe for every file: source, entry point, target, options and preprocessor definitions, in
the order they are passed. There are two pipelines:

- `dxc`: one `dxc -T <target> -E <entry> ... -Fo` invocation. 31 shaders use it.
- `dxc+packed16`: used by the two 64-channel refinement shaders `08155f47bc92811b.dxil` and `558c3931ba6fb064.dxil`.
  1. `dxc` writes the module's LLVM IR as text.
  2. A short pass in `build_profile.py` (`packed16`) points the coefficient loads at prepared 16-bit pairs and turns
     each 4-way int8 dot product into two 16-bit vector multiplies. The module becomes shader model 6.9.
  3. The release's own `opt`, `dxa` and `dxv` assemble, validate and sign the result.

| Source (`src/kernels/`) | Shaders |
| --- | --- |
| `wino_rs16.hlsl` | `1a3b0782583fef19`, `f030948d38e74671` |
| `wino_enc16.hlsl` | `e83e868f8d5d2c0f`, `9e0080eee00255f2`, `f2e2e13fea432d20`, `1f27b449fb99a587` |
| `wino_dec16.hlsl` | `b3941ac8ff95efe7`, `5654aa3800432b13`, `4bb52a635e6d221a` |
| `wino_row16.hlsl` | `60edebbbd2f9fb69`, `b3ddf030f661d487` |
| `wino_ref64.hlsl` | `wino-ref64-16`, `-17`, `-18` |
| `conv_wino4_prepare.hlsl` | `graph-prepare224`, `graph-prepare224-n32`, `graph-prepare64` |
| `conv_wino4_matmul.hlsl` | `graph-matmul224`, `graph-matmul224-n32`, `graph-matmul64` |
| `conv_wino4_finish.hlsl` | `graph-finish224(-17)(-n32)`, `graph-finish64-16`, `graph-finish64-17`, `mfg-finish*` (5) |
| `conv_64.hlsl` | `08155f47bc92811b`, `558c3931ba6fb064` (`dxc+packed16`) |

`conv_wino4_common.hlsli` is the header shared by the three `conv_wino4_*` passes.

Some files take their name from the bytecode hash of the runtime pipeline they replace (`<hash>.dxil`). Others are
helper passes the add-on dispatches itself (`graph-*`, `wino-ref64-*`, `mfg-finish*`).

The tables and markers are data and nothing compiles them:
- `waves.txt`: the wave size to request for each pipeline, by module hash (FNV-1a 64 of its bytes), 123 entries.
  It is the profile's table as pinned. Besides the 33 shaders here it therefore lists pipelines this directory does not
  hold: Intel's own pipelines, the Intel-derived replacements of the full profile that the Intel-free builds leave out,
  and four other own shaders. It holds hashes and wave sizes only. The multi-frame build ships it with twelve lines
  rewritten and 19 more lines (142 entries; below);
- `dispatch-scale.txt`: group-count scaling for replacements whose groups cover more output;
- the `*.required` markers: features the add-on checks for before it uses the profile.

`origin.json` gives a one-line description of every file.

## Which builds use which files

- The enabler-free 2x package (`intel-free-2x`) ships 37 of the 42 files.
- The five `mfg-finish*` shaders belong to the multi-frame network, which runs only at 3x/4x, so the 2x package drops
  them (`release/intel_free_2x.json`). They stay here because the Intel-free builds first copy every file of
  `release/intel_free.json`'s `keep` list and only then apply the 2x drop.
- `dispatch-scale.txt` is stored as pinned. The Intel-free builds remove one line from it while they build (the line for
  a replacement that is not part of this profile); the multi-frame build appends identity rows for the two U-Net row
  layers (`release/intel_free_mfg.json` `append_dispatch_scale`), so a dispatch bound to their F(4x4) pipeline gets its
  own group counts.
- `waves.txt` is stored as pinned (123 entries). The multi-frame build (`intel-free-mfg`) changes it while it builds:
  the lines of the twelve shaders it ships in another form name their new modules in place (below), five lines are
  appended (`release/intel_free_mfg.json` `append_waves`: wave 32 for five of Intel's unchanged pipelines, its 2x warps
  and one flow-path convolution, that run where the full profile had Intel-derived replacements), then the lines of
  F4Q's two kernels, F4Q2's three, F4Q3's two and the seven FP16 forms. Its package ships 142 entries, all of which the pacing layer reads; the add-on embeds that file's
  size and hash. Since 1.1.3.1 it also changes the existing `graph-prepare224.dxil` entry to wave64 through
  `wave_overrides`, without changing that shader's bytes or the number of entries. The 2x build ships the pinned table.

## The multi-frame build's own files (`release/profile-mfg/`)

The multi-frame build (`release/intel_free_mfg.json`, profile `replace` and `add`) ships 31 shaders that no other
build uses, from `release/profile-mfg/` (recipes in its `origin.json`, pinned in `release/inputs.lock.json` as the tree
group `profile-intel-free-mfg`; `build_profile.py check` rebuilds them too and reports them under `variant_profiles`):

- in place of nine files of this directory, the same U-Net shaders (`wino_rs16.hlsl`, `wino_enc16.hlsl`,
  `wino_dec16.hlsl`) compiled with `XU1=1` and `-enable-16bit-types`: the input transform in FP16 pairs, which hold its
  small integers exactly, so the products and sums are those of the FP32 form (the two `wino_row16.hlsl` shaders keep
  their recipe here);
- F4Q's F(4x4) kernels `b3941ac8ff95efe7.f4q.dxil` (`f4q_dec16.hlsl`) and `f030948d38e74671.f4q.dxil`
  (`f4q_enc16.hlsl`), loaded in place of the F(2x2) shaders of those two hashes while F4Q is on
  (`packaging/public/ARCHITECTURE.md`, "F4Q");
- the five check kernels of F4Q's diagnostic (`f4q-check-*.dxil`, `f4q_check.hlsl`);
- F4Q2's F(4x4) kernels `1a3b0782583fef19.f4q.dxil`, `e83e868f8d5d2c0f.f4q.dxil` and `9e0080eee00255f2.f4q.dxil`
  (`f4q_enc16.hlsl` with `CIN_SLICES` 1, 2 and 4), loaded in place of the F(2x2) shaders of those three hashes while F4Q
  and F4Q2 are on;
- since 1.1.2: F4Q's two kernels in their 1.1.2 form (`f4q_dec16.hlsl` with `XU2D=1 TRIM=1`, `f4q_enc16.hlsl` with
  `TRIM=1`: the same outputs); F4Q3's F(4x4) kernels `60edebbbd2f9fb69.f4q.dxil` and `b3ddf030f661d487.f4q.dxil`
  (`f4q_enc16.hlsl` with `POOL=0`), loaded in place of the row layers' 1D shaders while F4Q is on; in place of
  `wino-ref64-16/17/18.dxil`, the same kernel with `GX=16 ACC_SHR=1` (32 x 4 px groups, acc >> 2: the
  same outputs; the proxy dispatches it over the output size, `XEFG_REF64_GX16`);
- the seven FP16 forms `<hash>.fp16.dxil` (1.1.2's default; outputs differ slightly from the exact forms'): F4Q2's
  kernels with `HALF_TABLE=1` (FP16 U'/2 coefficient pairs), and the F(2x2) kernels of `1f27b449`, `f2e2e13f`,
  `5654aa38` and `4bb52a63` with `PK16=1` (packed-FP16 MACs, `pk16.hlsli`), each at the base of the FP16 copy its model
  owner writes (`src/model_f4q.h`).

This directory stays as it is, so the 2x build (0.9.0) and the enabler-era Intel-free add-on still build their
reference outputs.

The builds read this directory when neither `XEMFG_PROFILE` nor `XEMFG_WORK` is set, as in a checkout of the public
tree. To use it while a work directory is set, set `XEMFG_PROFILE` to it:

```sh
XEMFG_PROFILE=$PWD/release/profile python3 release/build_proxy.py
```

It is byte-identical to the build made from the pinned profile: the proxy, its embedded profile manifest and the
package files are the same.
