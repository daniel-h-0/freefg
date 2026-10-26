# Shader profile: origin and rebuild

This directory contains the base profile: **33 compute shaders and 9 tables/markers**. The public multi-frame build
replaces 12 shaders and adds 19 from `release/profile-mfg/`, producing **52 shaders and 9 tables/markers**.
All shaders come from this project's HLSL in `src/kernels/`. They contain no model weights; coefficients are read and
transformed in memory at runtime.

The build recipes and file hashes are in `origin.json` here and in `release/profile-mfg/origin.json`. The release lock
pins both sets. `release/intel_free_mfg.json` defines the replacements, additions and table edits.

## Rebuild and check

Download and extract Microsoft's
[DXC v1.9.2607 for Linux](https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/linux_dxc_2026_07_29.x86_x64.tar.gz):
515,588,543 bytes, SHA-256 `55665c87824051ed4774ff3280a79ccbbb7d39243b9736ca5e98222134112d54`.
From the repository root:

```sh
XEMFG_DXC=/path/to/linux_dxc_2026_07_29.x86_x64 python3 release/build_profile.py check
```

A complete rebuild reports `result: pass`, 33 byte-identical base shaders, and 31 under `variant_profiles`.
Another DXC version can produce different bytes. Without DXC, or with `--no-rebuild`, the command checks the stored
files and recipes but does not establish that they rebuilt.

The check verifies file sets, sizes, SHA-256 pins, shader models, wave-table entries, dispatch-scale entries and source
SPDX headers. It compiles into a temporary directory unless `--out` names one.

## Compile pipelines

Each recipe records its source, entry point, shader target, compiler options and definitions in argument order.

| Pipeline | Use |
| --- | --- |
| `dxc` | Direct HLSL compilation; 31 base shaders and all 31 variant shaders. |
| `dxc+packed16` | The base refinement shaders `08155f47bc92811b` and `558c3931ba6fb064`. Compile this project's HLSL to IR, redirect coefficient loads to prepared 16-bit pairs, replace each int8 dot product with packed 16-bit operations, then assemble/validate with DXC's `opt`, `dxa` and `dxv`. |

The packed16 transformation is exact when partial sums stay in range; the model owner checks that bound before using
those coefficients. It produces shader model 6.9. The other shipped shaders use model 6.6.

| HLSL family | Work |
| --- | --- |
| `wino_rs16`, `wino_enc16`, `wino_dec16`, `wino_row16` | U-Net replacements |
| `wino_ref64`, `conv_64` | Flow refinement |
| `conv_wino4_prepare`, `conv_wino4_matmul`, `conv_wino4_finish` | Winograd helper passes, including multi-frame variants |
| `f4q_enc16`, `f4q_dec16`, `f4q_check` | F(4×4) alternatives and diagnostic comparisons |

Files named `<hash>.dxil` replace a runtime pipeline with that bytecode hash. `graph-*`, `wino-ref64-*` and
`mfg-finish*` are helper passes dispatched by this project.

## Multi-frame variants

`release/profile-mfg/` contains:

- 12 replacements: nine U-Net shaders with exact packed input transforms (`XU1`) and three flow-refinement shaders
  with 32×4-pixel groups and an exact divide-by-four shift;
- seven F(4×4) alternatives: two F4Q, three F4Q2 and two F4Q3 kernels;
- seven FP16 alternatives, enabled by default: three F4Q2 kernels using rounded FP16 coefficient pairs and four U-Net
  kernels using packed FP16 multiply-adds;
- five diagnostic comparison kernels.

The FP16 alternatives can change generated pixels. F(4×4) paths matched in the reported comparisons but are not
proven equivalent for every input. [Arithmetic, switches and evidence](../../packaging/public/ARCHITECTURE.md#the-shader-profile).

## Tables and markers

- The base `waves.txt` has 123 entries. The multi-frame build replaces 12 module hashes and appends 19 entries,
  producing 142. Since 1.1.3.1, `wave_overrides` also selects wave64 for `graph-prepare224.dxil`; its shader bytes are
  unchanged. Entries include hashes of unchanged Intel shaders, not copies of those shaders.
- The build removes one unused `dispatch-scale.txt` row and appends identity rows for the two F4Q3 layers. The shipped
  table has 11 entries.
- Seven `*.required` markers enable parts of the accelerated path.

The base files retain the historical profile; the public build is `intel-free-mfg`. Build scripts read this directory
by default, or the directory named by `XEMFG_PROFILE`. Variant files always come from `release/profile-mfg/` in the tree.
