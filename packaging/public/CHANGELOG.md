# Changelog

Release summaries are below; [measurements](MEASUREMENTS.md) describe their specific test conditions. The
[detailed changelog at 1.1.6](https://github.com/daniel-h-0/freefg/blob/5de9a40317ff07511c69c006bad22b36d3250f03/packaging/public/CHANGELOG.md)
retains earlier release notes.

## 1.1.6 – 2026-10-30

- Update compatible installations in place, including OptiScaler, owned launcher fields and the selected upscaler.
  Import 1.1.3.1–1.1.5 records; retain original backups and a per-game rollback generation.
- Add HLX DLSS and HLX FSR 4 from locally prepared HelixSR 3.1.0. AMD FSR 4 remains a separate choice.
- Add Library selection, Register, Pin/Unpin, component updates and gameplay-qualified recipe refresh.
- Preserve user settings and report blocked, running or deferred games separately. Improve interruption recovery,
  drift checks and settings merges. No background updater is installed.
- Keep the 1.1.5 runtime and shader payload. [Checks and limits](MEASUREMENTS.md#checks-of-116).

## 1.1.5 – 2026-10-28

- Reduce scaling overhead by writing synthesis directly to the enlargement input, reusing colour-history reductions
  and allowing lossless compression. Simplify boundary reads without changing the scaling filters.
- Invalidate cached histories on writes, abandoned recordings and aliasing barriers. Restore original modification
  times when original file bytes have already returned.
- [Qualification and measurements](MEASUREMENTS.md#scaling-overhead-in-115).

## 1.1.4 – 2026-10-27

- Add generated-frame scaling: 50–100% or aspect-preserving 720p–2160p limits, with reduction and enlargement filters.
  Match output remains the default; real frames, depth and motion-vector inputs stay unchanged.
- Support bounded tiny, odd, portrait and ultrawide geometry and re-observation after layout changes. Add settings in
  Setup and OptiScaler and report actual scaling in Status. [Checks](MEASUREMENTS.md#generated-frame-scaling-in-114).

## 1.1.3.1 – 2026-10-25

- Select wave64 for the 224-channel input-transform shader after a wave32-associated GPU fault; shader arithmetic is
  unchanged and the cause remains unresolved. [Checks](MEASUREMENTS.md#checks-of-1131).
- Update OptiScaler to the 25 October source (`08e13adf`), retaining independent library paths and adaptive pacing.
  Update a game recipe and its scoped reactive-mask workaround.

## 1.1.3 – 2026-10-25

- Add adaptive game-frame starts at 3×/4× and factor-aware presentation jitter allowances; improve recovery after stalls.
- Fix OptiScaler's independent XeSS/XeFG/XeLL library-path handling and repair the known saved-path mix-up.
- Keep 1.1.2's shaders, Intel runtime and upscalers. [TV checks](MEASUREMENTS.md#checks-of-113).

## 1.1.2 – 2026-10-24

- Enable seven faster FP16 forms by default; they can change generated pixels. `Exact=1` or
  `BC250_XEFG_EXACT=1` disables them. Extend F4Q to additional encoder and row layers.
- Optimize exact transforms and install FSR 4 RC12. Report the selected output form and FSR build in Status.
  [Output and performance checks](MEASUREMENTS.md#checks-of-112).

## 1.1.1 – 2026-10-21

- Create a per-installation vkd3d cache and disable shader-module identifiers so wave overrides apply. Preserve
  explicit cache choices and omit the changes when the private path is too long.
- Set `XeFGModel=default` where unset and report full, partial or skipped acceleration. Runtime binaries remain 1.1.0's.
  [Cache checks](MEASUREMENTS.md#shader-caches).

## 1.1.0 – 2026-10-21

- Add exact packed input transforms, F4Q alternatives, their switches and diagnostic, and five Intel-shader wave32
  choices. Warm caches prevented the new wave choices from applying in the benchmark block; 1.1.1 addresses that.
  [Checks](MEASUREMENTS.md#checks-of-110).

## 1.0.1 – 2026-10-20

- Add a per-game anti-cheat override with explicit risk acceptance. Other refusals are unchanged. Runtime payloads
  match 1.0.0.

## 1.0.0 – 2026-10-20

- Add 3×/4× acceleration beside separately installed MFG Unlocker, caller-preserving coexistence and fallback for supported layout mismatches.
- Add HelixSR selection, offline compatibility checks, community/wiki guidance and conditional DLSS helper installation.
- Use SDK status to pace all frame counts, including Intel-shader fallback. [Checks](MEASUREMENTS.md#checks-of-100).

## 0.9.0 – 2026-10-19

- Introduce 2× BC-250 acceleration, gamescope pacing, FSR 4, Setup and CLI, launcher integration, Restore and
  optional system helpers. [Measurements](MEASUREMENTS.md).
